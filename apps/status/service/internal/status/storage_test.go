package status

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

func testStore(t *testing.T) *Store {
	t.Helper()
	s, err := Open(filepath.Join(t.TempDir(), "status.db"), bytes.Repeat([]byte{7}, 32))
	if err != nil {
		t.Fatal(err)
	}
	// Most store fixtures exercise an explicitly running observer. First-start
	// review is tested separately through Open without this fixture override.
	if _, err := s.db.Exec(`DELETE FROM settings WHERE key IN('probes_paused','outbox_paused')`); err != nil {
		s.Close()
		t.Fatal(err)
	}
	if _, err := s.db.Exec(`DELETE FROM audit_events WHERE actor='bootstrap' AND action='probes.pause'`); err != nil {
		s.Close()
		t.Fatal(err)
	}
	t.Cleanup(func() { s.Close() })
	return s
}
func TestStorageRefusesConcurrentOwnerAndWrongKey(t *testing.T) {
	path := filepath.Join(t.TempDir(), "status.db")
	key := bytes.Repeat([]byte{7}, 32)
	s, err := Open(path, key)
	if err != nil {
		t.Fatal(err)
	}
	if duplicate, err := Open(path, key); err == nil {
		duplicate.Close()
		t.Fatal("second scheduler owner accepted")
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	if wrong, err := Open(path, bytes.Repeat([]byte{8}, 32)); err == nil {
		wrong.Close()
		t.Fatal("wrong encryption key accepted")
	}
	reopened, err := Open(path, key)
	if err != nil {
		t.Fatal(err)
	}
	reopened.Close()
	info, err := os.Stat(path)
	if err != nil || info.Mode().Perm()&0077 != 0 {
		t.Fatal("database permissions allow other users")
	}
}
func TestStorageChecksDeclaredProducts(t *testing.T) {
	s := testStore(t)
	if _, err := s.db.Exec(`DROP INDEX idx_observations_time`); err != nil {
		t.Fatal(err)
	}
	if err := s.verify(); err == nil {
		t.Fatal("partial migration accepted")
	}
}
func TestCredentialEncryptionBindsIdentityAndKind(t *testing.T) {
	s := testStore(t)
	box, err := s.seal("credential", "deepseek", []byte("private-provider-key"))
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains([]byte(box), []byte("private-provider-key")) {
		t.Fatal("plaintext leaked")
	}
	raw, err := s.open("credential", "deepseek", box)
	if err != nil || string(raw) != "private-provider-key" {
		t.Fatal("round trip failed")
	}
	for _, pair := range [][2]string{{"different", "deepseek"}, {"credential", "qwen"}} {
		if _, err := s.open(pair[0], pair[1], box); err == nil {
			t.Fatal("foreign credential context opened")
		}
	}
}
