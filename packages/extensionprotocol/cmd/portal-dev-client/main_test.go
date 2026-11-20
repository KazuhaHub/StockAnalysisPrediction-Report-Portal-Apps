package main

import (
	"bytes"
	"encoding/json"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

// goldenRegistration is the exact file `register --key-hex 2323...23` writes for
// app "demo". A backend refuses a registration that is not byte-for-byte what
// it would marshal itself, so this pins the canonical field order. The same
// bytes are loaded by the backend template's own test.
const goldenRegistration = `{"format":"portal.managed-backend-registration/1-dev.1","metadata":{"identity":{"app_id":"demo","deployment_id":"portal-dev-local","controller_epoch":"00000000-0000-4000-8000-000000000d02","installation_id":"00000000-0000-4000-8000-000000000d01","generation":"1","policy_revision":"1","release_sha256":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"},"instance_id":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee","key_id":"5b19d45be03b87bdee0a7323ec312e8a11c89e91210d0cbe041e183ec111840f"},"signing_key":"IyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyM="}`

func TestRegisterWritesTheCanonicalFile(t *testing.T) {
	dir := t.TempDir()
	var out, errOut bytes.Buffer
	if code := run([]string{"register", "--dir", dir, "--app-id", "demo", "--key-hex", strings.Repeat("23", 32)}, &out, &errOut); code != 0 {
		t.Fatalf("%d %s", code, errOut.String())
	}
	raw, err := os.ReadFile(filepath.Join(dir, registrationName))
	if err != nil {
		t.Fatal(err)
	}
	var reg registration
	if err := json.Unmarshal(raw, &reg); err != nil {
		t.Fatal(err)
	}
	again, _ := json.Marshal(reg)
	if !bytes.Equal(again, raw) {
		t.Fatalf("not canonical:\n%s\n%s", raw, again)
	}
	if string(raw) != goldenRegistration {
		t.Fatalf("registration differs from the golden bytes:\n%s", raw)
	}
}

func TestRegisterKeepsAnExistingKey(t *testing.T) {
	dir := t.TempDir()
	var out, errOut bytes.Buffer
	run([]string{"register", "--dir", dir, "--app-id", "demo"}, &out, &errOut)
	first, _ := os.ReadFile(filepath.Join(dir, registrationName))
	run([]string{"register", "--dir", dir, "--app-id", "demo"}, &out, &errOut)
	second, _ := os.ReadFile(filepath.Join(dir, registrationName))
	if !bytes.Equal(first, second) {
		t.Fatal("a second register replaced the key under a running backend")
	}
}

func TestRefusesARegistrationItDidNotWrite(t *testing.T) {
	path := filepath.Join(t.TempDir(), registrationName)
	reg := newRegistration("demo", bytes.Repeat([]byte{7}, 32))
	reg.Metadata.Identity.DeploymentID = "10000000-0000-4000-8000-000000000005" // a Portal deployment
	raw, _ := json.Marshal(reg)
	if err := os.WriteFile(path, raw, 0o644); err != nil {
		t.Fatal(err)
	}
	var out, errOut bytes.Buffer
	if code := run([]string{"call", "--socket", "/nonexistent", "--registration", path, "GET", "/v1/x"}, &out, &errOut); code == 0 ||
		!strings.Contains(errOut.String(), "never works with a real one") {
		t.Fatalf("%d %q", code, errOut.String())
	}
}

// fakeBackend is the smallest backend: the handshake and viewer verification,
// built from the same protocol package a real backend uses.
func fakeBackend(t *testing.T, reg registration) string {
	t.Helper()
	const boot = "boot-1"
	signer := reg.signer(boot)
	verifier := protocol.NewVerifier(protocol.VerifyConfig{
		Issuer: signer.Issuer, Audience: signer.Audience, AppID: signer.AppID,
		InstanceID: signer.InstanceID, BootID: boot, Keys: map[string][]byte{signer.KeyID: signer.Key},
	})
	mux := http.NewServeMux()
	mux.HandleFunc("/v1/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/v1/handshake" {
			var req struct {
				Challenge string `json:"challenge"`
			}
			if json.NewDecoder(r.Body).Decode(&req) != nil {
				w.WriteHeader(400)
				return
			}
			answer, err := signer.AnswerChallenge(req.Challenge, boot, time.Now())
			if err != nil {
				w.WriteHeader(409)
				return
			}
			_ = json.NewEncoder(w).Encode(map[string]string{"answer": answer})
			return
		}
		if r.URL.Path == "/v1/tasks/run" {
			raw := r.Header.Get("X-Portal-Service-Identity")
			_ = json.NewEncoder(w).Encode(map[string]any{"identity_present": raw != "", "app_id": signer.AppID})
			return
		}
		body := new(bytes.Buffer)
		_, _ = body.ReadFrom(r.Body)
		claims, err := verifier.Verify(r.Header.Get(protocol.Header), r.Method, r.URL.RequestURI(), body.Bytes(), time.Now())
		if err != nil {
			w.WriteHeader(403)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"role": claims.Viewer.Role, "ous": claims.Viewer.OUs, "body": body.String()})
	})
	socket := filepath.Join(t.TempDir(), "app.sock")
	l, err := net.Listen("unix", socket)
	if err != nil {
		t.Fatal(err)
	}
	srv := &http.Server{Handler: mux}
	go srv.Serve(l)
	t.Cleanup(func() { srv.Close() })
	return socket
}

func TestCallHandshakesAndSignsTheViewerAssertion(t *testing.T) {
	dir := t.TempDir()
	var out, errOut bytes.Buffer
	if code := run([]string{"register", "--dir", dir, "--app-id", "demo"}, &out, &errOut); code != 0 {
		t.Fatal(errOut.String())
	}
	regPath := filepath.Join(dir, registrationName)
	reg, err := readRegistration(regPath)
	if err != nil {
		t.Fatal(err)
	}
	socket := fakeBackend(t, reg)
	bodyFile := filepath.Join(dir, "body.json")
	os.WriteFile(bodyFile, []byte(`{"a":1}`), 0o644)
	out.Reset()
	code := run([]string{"call", "--socket", socket, "--registration", regPath, "--role", "admin", "--ou", "ou-a", "--ou", "ou-b",
		"--body-file", bodyFile, "POST", "/v1/echo?x=1"}, &out, &errOut)
	if code != 0 || !strings.HasPrefix(out.String(), "HTTP 200\n") {
		t.Fatalf("%d %q %q", code, out.String(), errOut.String())
	}
	var body struct {
		Role string
		Ous  []string
		Body string
	}
	if err := json.Unmarshal([]byte(strings.TrimPrefix(out.String(), "HTTP 200\n")), &body); err != nil {
		t.Fatal(err)
	}
	if body.Role != "admin" || len(body.Ous) != 2 || body.Body != `{"a":1}` {
		t.Fatalf("%+v", body)
	}
	out.Reset()
	if code := run([]string{"task", "--socket", socket, "--registration", regPath, `{"job":"example"}`}, &out, &errOut); code != 0 ||
		!strings.Contains(out.String(), `"identity_present":true`) {
		t.Fatalf("%d %q %q", code, out.String(), errOut.String())
	}
}

func TestReadyAndPurge(t *testing.T) {
	dir := t.TempDir()
	var out, errOut bytes.Buffer
	run([]string{"register", "--dir", dir, "--app-id", "demo"}, &out, &errOut)
	reg, _ := readRegistration(filepath.Join(dir, registrationName))
	socket := fakeBackend(t, reg)
	out.Reset()
	// fakeBackend answers /v1/ only; an unknown route proves ready reports a non-200 as a failure.
	if code := run([]string{"ready", "--socket", socket}, &out, &errOut); code == 0 {
		t.Fatalf("a 404 counted as ready: %q", out.String())
	}
	os.MkdirAll(filepath.Join(dir, "sub/deeper"), 0o700)
	if code := run([]string{"purge", "--dir", dir}, &out, &errOut); code != 0 {
		t.Fatal(errOut.String())
	}
	if entries, _ := os.ReadDir(dir); len(entries) != 0 {
		t.Fatalf("left %v", entries)
	}
	if code := run([]string{"purge", "--dir", "/"}, &out, &errOut); code == 0 {
		t.Fatal("purge accepted /")
	}
}
