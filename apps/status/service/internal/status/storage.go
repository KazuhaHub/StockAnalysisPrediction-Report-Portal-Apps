package status

import (
	"bytes"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"database/sql"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"io"
	"net/url"
	"os"
	"path/filepath"
	"sync"

	_ "modernc.org/sqlite"
)

type Store struct {
	db          *sql.DB
	path        string
	key         []byte
	lock        *os.File
	maintenance sync.Mutex
	running     bool
}

func Open(path string, key []byte) (*Store, error) {
	if len(key) != 32 {
		return nil, errors.New("a 32-byte status storage key is required")
	}
	path, err := filepath.Abs(path)
	if err != nil {
		return nil, err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return nil, err
	}
	lock, err := lockVolume(path + ".lock")
	if err != nil {
		return nil, err
	}
	s := &Store{path: path, key: bytes.Clone(key), lock: lock}
	if err := s.openDB(); err != nil {
		s.Close()
		return nil, err
	}
	if err := s.migrate(); err != nil {
		s.Close()
		return nil, err
	}
	hash := sha256.Sum256(key)
	fingerprint := hex.EncodeToString(hash[:])
	existing := s.setting("storage_key_fingerprint")
	if existing != "" && existing != fingerprint {
		s.Close()
		return nil, errors.New("status storage key does not match the database")
	}
	if existing == "" {
		if _, err := s.db.Exec(`INSERT INTO settings(key,value) VALUES('storage_key_fingerprint',?)`, fingerprint); err != nil {
			s.Close()
			return nil, err
		}
	}
	return s, nil
}
func (s *Store) openDB() error {
	file, err := os.OpenFile(s.path, os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return err
	}
	file.Close()
	if err := os.Chmod(s.path, 0600); err != nil {
		return err
	}
	u := url.URL{Scheme: "file", Path: s.path}
	q := url.Values{}
	q.Add("_pragma", "foreign_keys(1)")
	q.Add("_pragma", "busy_timeout(5000)")
	q.Add("_pragma", "journal_mode(WAL)")
	u.RawQuery = q.Encode()
	db, err := sql.Open("sqlite", u.String())
	if err != nil {
		return err
	}
	db.SetMaxOpenConns(1)
	if err := db.Ping(); err != nil {
		db.Close()
		return err
	}
	s.db = db
	return nil
}
func (s *Store) Close() error {
	s.maintenance.Lock()
	defer s.maintenance.Unlock()
	var err error
	if s.db != nil {
		err = s.db.Close()
		s.db = nil
	}
	if s.lock != nil {
		releaseVolume(s.lock)
		s.lock = nil
	}
	return err
}
func (s *Store) seal(id, kind string, plain []byte) (string, error) {
	block, err := aes.NewCipher(s.key)
	if err != nil {
		return "", err
	}
	aead, err := cipher.NewGCM(block)
	if err != nil {
		return "", err
	}
	nonce := make([]byte, aead.NonceSize())
	if _, err := rand.Read(nonce); err != nil {
		return "", err
	}
	sealed := aead.Seal(nonce, nonce, plain, []byte("status-credential:v1:"+id+":"+kind))
	return "v1:" + base64.RawStdEncoding.EncodeToString(sealed), nil
}
func (s *Store) open(id, kind, sealed string) ([]byte, error) {
	if len(sealed) < 3 || sealed[:3] != "v1:" {
		return nil, errors.New("invalid sealed credential")
	}
	raw, err := base64.RawStdEncoding.Strict().DecodeString(sealed[3:])
	if err != nil {
		return nil, errors.New("invalid sealed credential")
	}
	block, err := aes.NewCipher(s.key)
	if err != nil {
		return nil, err
	}
	aead, err := cipher.NewGCM(block)
	if err != nil || len(raw) < aead.NonceSize() {
		return nil, errors.New("invalid sealed credential")
	}
	return aead.Open(nil, raw[:aead.NonceSize()], raw[aead.NonceSize():], []byte("status-credential:v1:"+id+":"+kind))
}
func (s *Store) Backup(destination string) error {
	s.maintenance.Lock()
	defer s.maintenance.Unlock()
	if s.db == nil {
		return errors.New("status store is closed")
	}
	if _, err := os.Lstat(destination); !os.IsNotExist(err) {
		return errors.New("backup destination already exists or is unavailable")
	}
	// VACUUM INTO takes a consistent snapshot including committed WAL contents.
	if _, err := s.db.Exec(`VACUUM INTO ?`, destination); err != nil {
		os.Remove(destination)
		return errors.New("status backup failed")
	}
	return os.Chmod(destination, 0600)
}

// Restore is an offline operation: callers must not start HTTP or workers first.
// The candidate is verified and paused before the live file is replaced.
func (s *Store) Restore(source string) error {
	s.maintenance.Lock()
	defer s.maintenance.Unlock()
	if s.running || s.db == nil {
		return errors.New("restore requires an offline status store")
	}
	in, err := os.Open(source)
	if err != nil {
		return errors.New("backup source unavailable")
	}
	defer in.Close()
	temp, err := os.CreateTemp(filepath.Dir(s.path), ".status-restore-*.db")
	if err != nil {
		return err
	}
	candidate := temp.Name()
	defer os.Remove(candidate)
	defer os.Remove(candidate + ".lock")
	n, copyErr := io.Copy(temp, io.LimitReader(in, 1<<30+1))
	syncErr := temp.Sync()
	closeErr := temp.Close()
	if copyErr != nil || syncErr != nil || closeErr != nil || n > 1<<30 {
		return errors.New("invalid or oversized status backup")
	}
	validated := &Store{path: candidate, key: bytes.Clone(s.key)}
	if err := validated.openDB(); err != nil {
		return err
	}
	if err := validated.verify(); err != nil {
		validated.Close()
		return err
	}
	if validated.setting("storage_key_fingerprint") != s.setting("storage_key_fingerprint") {
		validated.Close()
		return errors.New("backup encryption key does not match")
	}

	tx, err := validated.db.Begin()
	if err != nil {
		validated.Close()
		return err
	}
	for _, key := range []string{"probes_paused", "outbox_paused"} {
		if err := setSetting(tx, key, "1"); err != nil {
			tx.Rollback()
			validated.Close()
			return err
		}
	}
	statements := []string{
		`INSERT INTO settings(key,value) VALUES('public_enabled','0') ON CONFLICT(key) DO UPDATE SET value='0'`,
		`UPDATE monitors SET lease_token='',lease_until=0,revision=revision+1`,
		`UPDATE monitor_states SET current_state='unknown',success_streak=0,failure_streak=0`,
		`UPDATE notification_outbox SET state=CASE WHEN attempts>0 OR state='leased' THEN 'review_required' ELSE state END,lease_token='',lease_until=0 WHERE state<>'delivered'`,
		`UPDATE notification_publishers SET enabled=0,revision=revision+1`,
	}
	for _, q := range statements {
		if _, err := tx.Exec(q); err != nil {
			tx.Rollback()
			validated.Close()
			return err
		}
	}
	if err := tx.Commit(); err != nil {
		validated.Close()
		return err
	}
	if err := validated.Close(); err != nil {
		return err
	}
	// Close checkpoints the current WAL. Keep the prior database for rollback.
	if err := s.db.Close(); err != nil {
		return err
	}
	s.db = nil
	rollback := s.path + ".pre-restore"
	if _, err := os.Lstat(rollback); !os.IsNotExist(err) {
		s.openDB()
		return errors.New("preserve or remove the previous rollback backup before restoring")
	}
	if err := os.Rename(s.path, rollback); err != nil {
		s.openDB()
		return err
	}
	if err := os.Rename(candidate, s.path); err != nil {
		os.Rename(rollback, s.path)
		s.openDB()
		return err
	}
	if err := s.openDB(); err != nil {
		os.Remove(s.path)
		os.Rename(rollback, s.path)
		s.openDB()
		return errors.New("restored database could not be opened; prior database retained")
	}
	return nil
}
