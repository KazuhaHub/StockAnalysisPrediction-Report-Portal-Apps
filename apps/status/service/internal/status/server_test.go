package status

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

func handshakeRequest(t *testing.T, signer protocol.Signer) (*http.Request, string) {
	t.Helper()
	challenge, err := signer.NewChallenge(time.Now())
	if err != nil {
		t.Fatal(err)
	}
	body, _ := json.Marshal(map[string]string{"challenge": challenge})
	request := httptest.NewRequest(http.MethodPost, "http://portal-app.invalid/v1/handshake", bytes.NewReader(body))
	request.Header.Set("Content-Type", "application/json")
	return request, challenge
}

func TestReadyEndpointIsStrictAndChecksStorage(t *testing.T) {
	store := testStore(t)
	server, _ := newTestServer(t, store)
	call := func(mutate func(*http.Request)) *httptest.ResponseRecorder {
		request := httptest.NewRequest(http.MethodGet, "http://portal-app.invalid/health/ready", nil)
		if mutate != nil {
			mutate(request)
		}
		recorder := httptest.NewRecorder()
		server.ServeHTTP(recorder, request)
		return recorder
	}
	ready := call(nil)
	if ready.Code != http.StatusOK || !strings.Contains(ready.Body.String(), `"ready":true`) || !strings.Contains(ready.Body.String(), `"protocol":"portal.backend/1"`) {
		t.Fatalf("ready = %d %s", ready.Code, ready.Body.String())
	}
	for name, mutate := range map[string]func(*http.Request){
		"query":         func(r *http.Request) { r.URL.RawQuery = "probe=1" },
		"cookie":        func(r *http.Request) { r.Header.Set("Cookie", "session=private") },
		"authorization": func(r *http.Request) { r.Header.Set("Authorization", "Bearer private") },
	} {
		if recorder := call(mutate); recorder.Code != http.StatusBadRequest {
			t.Errorf("%s ready = %d", name, recorder.Code)
		}
	}
	post := httptest.NewRecorder()
	server.ServeHTTP(post, httptest.NewRequest(http.MethodPost, "http://portal-app.invalid/health/ready", nil))
	if post.Code != http.StatusNotFound {
		t.Fatalf("POST ready = %d", post.Code)
	}
	if err := store.db.Close(); err != nil {
		t.Fatal(err)
	}
	if recorder := call(nil); recorder.Code != http.StatusServiceUnavailable {
		t.Fatalf("ready with unavailable storage = %d", recorder.Code)
	}
}

func TestHandshakeBindsRegistrationKeyAndBoot(t *testing.T) {
	server, signer := newTestServer(t, testStore(t))
	request, challenge := handshakeRequest(t, signer)
	recorder := httptest.NewRecorder()
	server.ServeHTTP(recorder, request)
	if recorder.Code != http.StatusOK {
		t.Fatalf("handshake = %d %s", recorder.Code, recorder.Body.String())
	}
	var response struct {
		Answer string `json:"answer"`
	}
	if json.Unmarshal(recorder.Body.Bytes(), &response) != nil || response.Answer == "" {
		t.Fatalf("handshake answer = %s", recorder.Body.String())
	}
	bootID, err := signer.VerifyAnswer(challenge, response.Answer, time.Now())
	if err != nil || bootID != testBootID {
		t.Fatalf("handshake boot = %q, %v", bootID, err)
	}
	wrong := signer
	wrong.Key = bytes.Clone(signer.Key)
	wrong.Key[0] ^= 1
	wrongRequest, _ := handshakeRequest(t, wrong)
	wrongRecorder := httptest.NewRecorder()
	server.ServeHTTP(wrongRecorder, wrongRequest)
	if wrongRecorder.Code != http.StatusBadRequest {
		t.Fatalf("wrong-key handshake = %d %s", wrongRecorder.Code, wrongRecorder.Body.String())
	}
}

func TestHandshakeRefusesChangedRegistrationAndMalformedRequests(t *testing.T) {
	registration := testRegistration()
	path := writeTestRegistration(t, registration)
	server := NewServer(testStore(t), path, testBootID)
	signer, err := registration.Signer(testBootID)
	if err != nil {
		t.Fatal(err)
	}
	changed := registration
	changed.Key = bytes.Clone(registration.Key)
	changed.Key[0] ^= 1
	raw, _ := json.Marshal(changed)
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	request, _ := handshakeRequest(t, signer)
	recorder := httptest.NewRecorder()
	server.ServeHTTP(recorder, request)
	if recorder.Code != http.StatusServiceUnavailable {
		t.Fatalf("changed registration handshake = %d %s", recorder.Code, recorder.Body.String())
	}
	raw, _ = json.Marshal(registration)
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	for name, mutate := range map[string]func(*http.Request){
		"query":         func(r *http.Request) { r.URL.RawQuery = "redirect=https://example.invalid" },
		"cookie":        func(r *http.Request) { r.Header.Set("Cookie", "session=private") },
		"authorization": func(r *http.Request) { r.Header.Set("Authorization", "Bearer private") },
		"content type":  func(r *http.Request) { r.Header.Set("Content-Type", "text/plain") },
		"unknown field": func(r *http.Request) {
			r.Body = io.NopCloser(strings.NewReader(`{"challenge":"a.b","redirect":"private"}`))
		},
		"invalid challenge": func(r *http.Request) { r.Body = io.NopCloser(strings.NewReader(`{"challenge":"private"}`)) },
		"empty body":        func(r *http.Request) { r.Body = io.NopCloser(strings.NewReader(``)) },
	} {
		t.Run(name, func(t *testing.T) {
			request, _ := handshakeRequest(t, signer)
			mutate(request)
			recorder := httptest.NewRecorder()
			server.ServeHTTP(recorder, request)
			if recorder.Code != http.StatusBadRequest {
				t.Fatalf("refused handshake = %d %s", recorder.Code, recorder.Body.String())
			}
		})
	}
}

func TestOnlyPlatformRoutesAreServed(t *testing.T) {
	server, signer := newTestServer(t, testStore(t))
	get := httptest.NewRecorder()
	server.ServeHTTP(get, httptest.NewRequest(http.MethodGet, "http://portal-app.invalid/v1/handshake", nil))
	if get.Code != http.StatusNotFound {
		t.Fatalf("GET handshake = %d", get.Code)
	}
	legacy := httptest.NewRecorder()
	server.ServeHTTP(legacy, httptest.NewRequest(http.MethodGet, "http://portal-app.invalid/healthz", nil))
	if legacy.Code == http.StatusOK {
		t.Fatal("legacy health route still served")
	}
	// Public pages, readiness aliases and heartbeat ingress belong to a later
	// phase: with public publication switched on, none is reachable.
	if _, err := server.store.db.Exec(`INSERT INTO settings VALUES('public_enabled','1')`); err != nil {
		t.Fatal(err)
	}
	for _, c := range []struct{ method, path string }{
		{"GET", "/readyz"}, {"GET", "/public/v1/status"}, {"GET", "/public/v1/history"}, {"GET", "/public/v1/incidents"},
		{"GET", "/"}, {"GET", "/app.js"}, {"GET", "/style.css"}, {"POST", "/ingest/v1/heartbeats/any"},
	} {
		request := httptest.NewRequest(c.method, "http://portal-app.invalid"+c.path, strings.NewReader(`{}`))
		recorder := httptest.NewRecorder()
		server.ServeHTTP(recorder, request)
		if recorder.Code != http.StatusNotFound {
			t.Errorf("%s %s = %d, want 404", c.method, c.path, recorder.Code)
		}
	}
	// Task and event handlers belong to a later phase: even an administrator's
	// authenticated call reaches no handler.
	for _, path := range []string{"/v1/tasks/run", "/v1/events/subscribe"} {
		token, err := signer.Sign("POST", path, []byte(`{}`), fixtureAdmin(), time.Now())
		if err != nil {
			t.Fatal(err)
		}
		request := httptest.NewRequest(http.MethodPost, "http://portal-app.invalid"+path, strings.NewReader(`{}`))
		request.Header.Set(protocol.Header, token)
		recorder := httptest.NewRecorder()
		server.ServeHTTP(recorder, request)
		if recorder.Code != http.StatusNotFound {
			t.Errorf("POST %s = %d %s", path, recorder.Code, recorder.Body.String())
		}
	}
}

func TestPrivateAPIRequiresBoundAssertionsAndCurrentBoot(t *testing.T) {
	store := testStore(t)
	server, signer := newTestServer(t, store)
	viewer := fixtureViewer("user", "viewer", "team")
	call := func(target *Server, token, method, path string) *httptest.ResponseRecorder {
		r := httptest.NewRequest(method, path, nil)
		if token != "" {
			r.Header.Set(protocol.Header, token)
		}
		w := httptest.NewRecorder()
		target.ServeHTTP(w, r)
		return w
	}
	sign := func(s protocol.Signer, v protocol.Viewer, path string) string {
		token, err := s.Sign("GET", path, nil, v, time.Now())
		if err != nil {
			t.Fatal(err)
		}
		return token
	}
	if w := call(server, "", "GET", "/v1/components"); w.Code != 403 {
		t.Fatal("unsigned request accepted")
	}
	assertion := sign(signer, viewer, "/v1/components")
	if w := call(server, assertion, "GET", "/v1/components"); w.Code != 200 {
		t.Fatalf("read=%d %s", w.Code, w.Body.String())
	}
	if w := call(server, assertion, "GET", "/v1/components"); w.Code != 403 {
		t.Fatal("replay accepted")
	}
	otherBoot := signer
	otherBoot.BootID = strings.Repeat("c", 32)
	if w := call(server, sign(otherBoot, viewer, "/v1/components"), "GET", "/v1/components"); w.Code != 403 {
		t.Fatal("assertion for another boot accepted")
	}
	restarted := NewServer(store, server.registration, strings.Repeat("c", 32))
	if w := call(restarted, sign(signer, viewer, "/v1/components"), "GET", "/v1/components"); w.Code != 403 {
		t.Fatal("old boot accepted after restart")
	}
	if w := call(server, sign(signer, viewer, "/v1/manage/components"), "GET", "/v1/manage/components"); w.Code != 403 {
		t.Fatal("reader saw management configuration")
	}
	legacy := protocol.Viewer{Subject: "admin", Role: "admin"}
	if w := call(server, sign(signer, legacy, "/v1/manage/components"), "GET", "/v1/manage/components"); w.Code != 403 {
		t.Fatalf("non-platform identity = %d", w.Code)
	}
	if w := call(server, sign(signer, fixtureAdmin(), "/v1/manage/components"), "GET", "/v1/manage/components"); w.Code != 200 {
		t.Fatalf("administrator management = %d", w.Code)
	}
}

func TestPrivateAPIUnavailableWithoutCurrentRegistration(t *testing.T) {
	store := testStore(t)
	server, signer := newTestServer(t, store)
	token, err := signer.Sign("GET", "/v1/components", nil, fixtureViewer("user", "viewer"), time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(server.registration); err != nil {
		t.Fatal(err)
	}
	r := httptest.NewRequest("GET", "/v1/components", nil)
	r.Header.Set(protocol.Header, token)
	w := httptest.NewRecorder()
	server.ServeHTTP(w, r)
	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("missing registration = %d", w.Code)
	}
}

// The platform relay passes a backend answer on only for 2xx and 400, 403, 404,
// 409, 422 and 429. A rejected viewer or assertion is a 403 with a JSON body;
// a registration the service cannot read is the same 503 the handshake gives.
func TestRejectedPrivateRequestsUseRelayableStatuses(t *testing.T) {
	store := testStore(t)
	server, signer := newTestServer(t, store)
	unsigned := httptest.NewRecorder()
	server.ServeHTTP(unsigned, httptest.NewRequest("GET", "/v1/components", nil))
	if unsigned.Code != http.StatusForbidden || !json.Valid(unsigned.Body.Bytes()) {
		t.Fatalf("unsigned = %d %q", unsigned.Code, unsigned.Body.String())
	}
	forged := httptest.NewRequest("GET", "/v1/components", nil)
	forged.Header.Set(protocol.Header, "not-an-assertion")
	forgedResponse := httptest.NewRecorder()
	server.ServeHTTP(forgedResponse, forged)
	if forgedResponse.Code != http.StatusForbidden {
		t.Fatalf("forged = %d", forgedResponse.Code)
	}
	noAuthority := fixtureViewer("user", "nobody")
	noAuthority.Subject = "not-opaque"
	token, err := signer.Sign("GET", "/v1/components", nil, noAuthority, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	rejected := httptest.NewRequest("GET", "/v1/components", nil)
	rejected.Header.Set(protocol.Header, token)
	rejectedResponse := httptest.NewRecorder()
	server.ServeHTTP(rejectedResponse, rejected)
	if rejectedResponse.Code != http.StatusForbidden {
		t.Fatalf("viewer without authority = %d", rejectedResponse.Code)
	}
	missing := NewServer(store, filepath.Join(t.TempDir(), "absent.json"), testBootID)
	request := httptest.NewRequest("GET", "/v1/components", nil)
	request.Header.Set(protocol.Header, "assertion")
	response := httptest.NewRecorder()
	missing.ServeHTTP(response, request)
	if response.Code != http.StatusServiceUnavailable {
		t.Fatalf("unreadable registration = %d", response.Code)
	}
}
