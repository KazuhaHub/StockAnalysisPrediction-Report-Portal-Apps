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
