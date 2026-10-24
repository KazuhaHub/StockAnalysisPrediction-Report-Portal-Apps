package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestOfflineCommandsGenerateKeyBackupAndRestore(t *testing.T) {
	dir := t.TempDir()
	key := filepath.Join(dir, "storage.key")
	database := filepath.Join(dir, "status.db")
	backup := filepath.Join(dir, "backup.db")
	previous := os.Args
	defer func() { os.Args = previous }()
	invoke := func(args ...string) error { os.Args = append([]string{"status"}, args...); return run() }
	if err := invoke("keygen", "-file", key); err != nil {
		t.Fatal(err)
	}
	if err := invoke("keygen", "-file", key); err == nil {
		t.Fatal("existing key overwritten")
	}
	if err := invoke("backup", "-database", database, "-storage-key-file", key, "-file", backup); err != nil {
		t.Fatal(err)
	}
	if err := invoke("restore", "-database", database, "-storage-key-file", key, "-file", backup); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(database + ".pre-restore"); err != nil {
		t.Fatal("rollback backup not retained")
	}
	if err := os.Chmod(key, 0644); err != nil {
		t.Fatal(err)
	}
	if err := invoke("backup", "-database", database, "-storage-key-file", key, "-file", filepath.Join(dir, "unsafe.db")); err == nil {
		t.Fatal("world-readable key file accepted")
	}
}
