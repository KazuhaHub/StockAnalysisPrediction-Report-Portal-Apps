package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestKeygenRefusesToOverwriteAndOfflineSnapshotCommandsAreGone(t *testing.T) {
	dir := t.TempDir()
	key := filepath.Join(dir, "storage.key")
	previous := os.Args
	defer func() { os.Args = previous }()
	invoke := func(args ...string) error { os.Args = append([]string{"status"}, args...); return run() }
	if err := invoke("keygen", "-file", key); err != nil {
		t.Fatal(err)
	}
	if err := invoke("keygen", "-file", key); err == nil {
		t.Fatal("existing key overwritten")
	}
	for _, command := range []string{"backup", "restore"} {
		if err := invoke(command, "-database", filepath.Join(dir, "status.db"), "-storage-key-file", key, "-file", filepath.Join(dir, "x.db")); err == nil {
			t.Fatalf("%s command still accepted", command)
		}
	}
	if _, err := os.Stat(filepath.Join(dir, "x.db")); err == nil {
		t.Fatal("snapshot written")
	}
}
