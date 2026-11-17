package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

func TestRemovedPairingListenAndOfflineSnapshotInterfacesAreRefused(t *testing.T) {
	previous := os.Args
	defer func() { os.Args = previous }()
	for _, args := range [][]string{
		{"serve", "-listen", ":8791"},
		{"serve", "-pairing-file", "/nonexistent"},
		{"serve", "-storage-key-file", "/nonexistent"},
		{"keygen", "-file", filepath.Join(t.TempDir(), "key")},
		{"backup", "-file", filepath.Join(t.TempDir(), "x.db")},
		{"restore", "-file", filepath.Join(t.TempDir(), "x.db")},
	} {
		os.Args = append([]string{"status"}, args...)
		if err := run(); err == nil {
			t.Errorf("%v accepted", args)
		}
	}
}

func testRegistrationFile(t *testing.T, directory string) (string, protocol.Signer) {
	t.Helper()
	key := bytes.Repeat([]byte{0x23}, 32)
	sum := sha256.Sum256(key)
	// Field order is the platform's canonical order, which the service requires.
	raw := []byte(fmt.Sprintf(`{"format":"portal.managed-backend-registration/1-dev.1","metadata":{"identity":{"app_id":"status","deployment_id":"10000000-0000-4000-8000-000000000005","controller_epoch":"10000000-0000-4000-8000-000000000004","installation_id":"10000000-0000-4000-8000-000000000001","generation":"1","policy_revision":"1","release_sha256":"%s"},"instance_id":"%s","key_id":"%s"},"signing_key":"%s"}`,
		strings.Repeat("a", 64), strings.Repeat("d", 64), hex.EncodeToString(sum[:]), base64.StdEncoding.EncodeToString(key)))
	path := filepath.Join(directory, "registration.json")
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	return path, protocol.Signer{
		Issuer: "portal.app/10000000-0000-4000-8000-000000000005", Audience: "portal.app/10000000-0000-4000-8000-000000000001",
		AppID: "status", InstanceID: strings.Repeat("d", 64), KeyID: hex.EncodeToString(sum[:]), Key: key,
	}
}

func TestServeAnswersTheHandshakeOnTheUnixSocketOnly(t *testing.T) {
	directory, err := os.MkdirTemp(os.Getenv("TMPDIR"), "s")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(directory)
	registration, signer := testRegistrationFile(t, directory)
	socket := filepath.Join(directory, "app.sock")
	t.Setenv("PORTAL_APP_HTTP_SOCKET", socket)
	cfg := config{database: filepath.Join(directory, "data", "status.db"), registration: registration, socket: socket}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- serve(ctx, cfg) }()
	client := &http.Client{Timeout: 5 * time.Second, Transport: &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "unix", socket)
	}}}
	var ready *http.Response
	for range 100 {
		ready, err = client.Get("http://portal-app.invalid/health/ready")
		if err == nil {
			break
		}
		time.Sleep(50 * time.Millisecond)
	}
	if err != nil || ready.StatusCode != 200 {
		t.Fatalf("ready %v %v", ready, err)
	}
	ready.Body.Close()
	challenge, err := signer.NewChallenge(time.Now())
	if err != nil {
		t.Fatal(err)
	}
	body, _ := json.Marshal(map[string]string{"challenge": challenge})
	request, _ := http.NewRequest("POST", "http://portal-app.invalid/v1/handshake", bytes.NewReader(body))
	request.Header.Set("Content-Type", "application/json")
	response, err := client.Do(request)
	if err != nil || response.StatusCode != 200 {
		t.Fatalf("handshake %v %v", response, err)
	}
	var answer struct {
		Answer string `json:"answer"`
	}
	json.NewDecoder(response.Body).Decode(&answer)
	response.Body.Close()
	if boot, err := signer.VerifyAnswer(challenge, answer.Answer, time.Now()); err != nil || len(boot) != 32 {
		t.Fatalf("boot=%q err=%v", boot, err)
	}
	if info, err := os.Stat(socket); err != nil || info.Mode().Perm() != 0600 {
		t.Fatalf("socket mode %v %v", info, err)
	}
	cancel()
	if err := <-done; err != nil {
		t.Fatalf("serve stopped with %v", err)
	}
	// Restart over the same data: the storage key and database are reused.
	ctx, cancel = context.WithCancel(context.Background())
	done = make(chan error, 1)
	go func() { done <- serve(ctx, cfg) }()
	for range 100 {
		if r, err := client.Get("http://portal-app.invalid/health/ready"); err == nil {
			r.Body.Close()
			break
		}
		time.Sleep(50 * time.Millisecond)
	}
	cancel()
	if err := <-done; err != nil {
		t.Fatalf("restart stopped with %v", err)
	}
	if info, err := os.Stat(filepath.Join(directory, "data", "status.key")); err != nil || info.Mode().Perm() != 0600 {
		t.Fatalf("storage key %v %v", info, err)
	}
}

func TestServeRefusesAnUnreadableRegistrationBeforeListening(t *testing.T) {
	directory, err := os.MkdirTemp(os.Getenv("TMPDIR"), "s")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(directory)
	socket := filepath.Join(directory, "app.sock")
	cfg := config{database: filepath.Join(directory, "status.db"), registration: filepath.Join(directory, "missing.json"), socket: socket}
	if err := serve(context.Background(), cfg); err == nil {
		t.Fatal("served without a platform registration")
	}
	if _, err := os.Stat(socket); err == nil {
		t.Fatal("listened without a platform registration")
	}
}

func TestStorageKeyIsCreatedOnceWithOwnerOnlyPermissions(t *testing.T) {
	directory := t.TempDir()
	keyPath := filepath.Join(directory, storageKeyName)
	first, err := loadStorageKey(keyPath, filepath.Join(directory, "status.db"))
	if err != nil || len(first) != 32 {
		t.Fatalf("first key = %d bytes, %v", len(first), err)
	}
	info, err := os.Stat(keyPath)
	if err != nil || info.Mode().Perm() != 0600 {
		t.Fatalf("key file = %v, %v", info, err)
	}
	second, err := loadStorageKey(keyPath, filepath.Join(directory, "status.db"))
	if err != nil || !bytes.Equal(first, second) {
		t.Fatalf("key changed between loads: %v", err)
	}
	entries, err := os.ReadDir(directory)
	if err != nil || len(entries) != 1 {
		t.Fatalf("temporary key files left behind: %v %v", entries, err)
	}
}

func TestStorageKeyIsNeverRegeneratedOverAnExistingDatabase(t *testing.T) {
	for name, prepare := range map[string]func(string){
		"missing": func(string) {},
		"empty":   func(keyPath string) { os.WriteFile(keyPath, nil, 0600) },
	} {
		t.Run(name, func(t *testing.T) {
			directory := t.TempDir()
			database := filepath.Join(directory, "status.db")
			if err := os.WriteFile(database, []byte("sealed rows"), 0600); err != nil {
				t.Fatal(err)
			}
			keyPath := filepath.Join(directory, storageKeyName)
			prepare(keyPath)
			if key, err := loadStorageKey(keyPath, database); err == nil {
				t.Fatalf("a key was produced beside an existing database: %d bytes", len(key))
			}
			if info, err := os.Stat(keyPath); name == "missing" && err == nil {
				t.Fatalf("a key file was created: %v", info)
			} else if name == "empty" && err == nil && info.Size() != 0 {
				t.Fatal("the empty key file was overwritten")
			}
		})
	}
}
