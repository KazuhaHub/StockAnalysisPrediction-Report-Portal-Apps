package status

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

// The platform supplies opaque, installation-scoped identifiers: a 64-character
// lowercase hex subject and one such identifier per actual OU ancestor. Fixtures
// derive the same shape from readable names so tests stay legible.
func fixtureOpaque(purpose, name string) string {
	sum := sha256.Sum256([]byte("status-fixture\x00" + purpose + "\x00" + name))
	return hex.EncodeToString(sum[:])
}

func fixtureViewer(role, name string, ous ...string) protocol.Viewer {
	viewer := protocol.Viewer{Subject: fixtureOpaque("account", name), Role: role, OUs: []string{}}
	for _, ou := range ous {
		viewer.OUs = append(viewer.OUs, fixtureOpaque("ou", ou))
	}
	return viewer
}

func fixtureAdmin() protocol.Viewer { return fixtureViewer("admin", "admin") }

// fixtureOU is the grant principal for a fixture OU.
func fixtureOU(name string) string { return "ou:" + fixtureOpaque("ou", name) }

const (
	testBootID       = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
	testInstallation = "10000000-0000-4000-8000-000000000001"
	testEpoch        = "10000000-0000-4000-8000-000000000004"
)

func testRegistration() backendRegistration {
	key := bytes.Repeat([]byte{0x23}, 32)
	sum := sha256.Sum256(key)
	var registration backendRegistration
	registration.Format = backendRegistrationFormat
	registration.Metadata.Identity.AppID = applicationID
	registration.Metadata.Identity.DeploymentID = "10000000-0000-4000-8000-000000000005"
	registration.Metadata.Identity.ControllerEpoch = testEpoch
	registration.Metadata.Identity.InstallationID = testInstallation
	registration.Metadata.Identity.Generation = "1"
	registration.Metadata.Identity.PolicyRevision = "1"
	registration.Metadata.Identity.ReleaseSHA256 = strings.Repeat("a", 64)
	registration.Metadata.InstanceID = strings.Repeat("d", 64)
	registration.Metadata.KeyID = hex.EncodeToString(sum[:])
	registration.Key = key
	return registration
}

func writeTestRegistration(t *testing.T, registration backendRegistration) string {
	t.Helper()
	raw, err := json.Marshal(registration)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "registration.json")
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	return path
}

// newTestServer serves a store behind a platform registration. The returned
// signer is the platform side: it answers for assertions bound to this boot.
func newTestServer(t *testing.T, store *Store) (*Server, protocol.Signer) {
	t.Helper()
	registration := testRegistration()
	server := NewServer(store, writeTestRegistration(t, registration), testBootID)
	signer, err := registration.Signer(testBootID)
	if err != nil {
		t.Fatal(err)
	}
	return server, signer
}

// phase2Handler serves the unregistered public and heartbeat routes so their
// own behaviour stays under test until Phase 2 registers them.
func phase2Handler(s *Server) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(http.MaxBytesReader(w, r.Body, 65536))
		if !s.servePhase2(w, r, raw) {
			http.NotFound(w, r)
		}
	})
}
