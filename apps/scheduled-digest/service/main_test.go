package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

const (
	testInstallation = "10000000-0000-4000-8000-000000000001"
	testTaskID       = "10000000-0000-4000-8000-000000000002"
	testLeaseID      = "10000000-0000-4000-8000-000000000003"
	testEpoch        = "10000000-0000-4000-8000-000000000004"
	testRelease      = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
)

func testRegistration(t *testing.T) backendRegistration {
	t.Helper()
	key := bytes.Repeat([]byte{0x23}, 32)
	sum := sha256.Sum256(key)
	var registration backendRegistration
	registration.Format = backendRegistrationFmt
	registration.Metadata.Identity.AppID = applicationID
	registration.Metadata.Identity.DeploymentID = "10000000-0000-4000-8000-000000000005"
	registration.Metadata.Identity.ControllerEpoch = testEpoch
	registration.Metadata.Identity.InstallationID = testInstallation
	registration.Metadata.Identity.Generation = "1"
	registration.Metadata.Identity.PolicyRevision = "1"
	registration.Metadata.Identity.ReleaseSHA256 = testRelease
	registration.Metadata.InstanceID = strings.Repeat("d", 64)
	registration.Metadata.KeyID = hex.EncodeToString(sum[:])
	registration.Key = key
	return registration
}

func testApplication(t *testing.T) (application, backendRegistration) {
	t.Helper()
	root := t.TempDir()
	registration := testRegistration(t)
	raw, err := json.Marshal(registration)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(
		filepath.Join(root, "registration.json"),
		raw, 0600); err != nil {
		t.Fatal(err)
	}
	store := newDigestStore(filepath.Join(root, "state.json"))
	store.now = func() time.Time {
		return time.Date(2026, 11, 3, 23, 0, 0, 0, time.UTC)
	}
	return application{
		store: store, registration: filepath.Join(root, "registration.json"),
		bootID: strings.Repeat("b", 32),
	}, registration
}

func testIdentity(resources []string, now time.Time) string {
	raw, _ := json.Marshal(serviceIdentity{
		Format: serviceIdentityFormat, LeaseID: testLeaseID,
		AppID: applicationID, InstallationID: testInstallation,
		ControllerEpoch: testEpoch, Generation: "1", PolicyRevision: "1",
		ReleaseSHA256: testRelease, Resources: resources,
		IssuedMS:  strconv.FormatInt(now.Add(-time.Second).UnixMilli(), 10),
		ExpiresMS: strconv.FormatInt(now.Add(time.Minute).UnixMilli(), 10),
		Mac:       strings.Repeat("a", 64),
	})
	return string(raw)
}

func taskBody(t *testing.T, payload string) []byte {
	t.Helper()
	raw, err := json.Marshal(taskRequest{
		Format: taskRequestFormat, TaskID: testTaskID,
		OccurrenceID: "digest:2026-11-03", Payload: json.RawMessage(payload),
	})
	if err != nil {
		t.Fatal(err)
	}
	return raw
}

func TestDigestTaskIsIdempotentAndBoundToServiceAuthority(t *testing.T) {
	app, _ := testApplication(t)
	now := time.Now()
	identity := testIdentity([]string{"reports.read", "tasks.schedule"}, now)
	body := taskBody(t, `{"scheduleId":"daily","reportIds":[41,42]}`)
	run := func(payload []byte, identity string) *httptest.ResponseRecorder {
		request := httptest.NewRequest(
			http.MethodPost, "http://portal-app.invalid/v1/tasks/digest",
			bytes.NewReader(payload))
		request.Header.Set("Content-Type", "application/json")
		request.Header.Set("X-Portal-Service-Identity", identity)
		recorder := httptest.NewRecorder()
		app.ServeHTTP(recorder, request)
		return recorder
	}
	first := run(body, identity)
	if first.Code != http.StatusOK ||
		!strings.Contains(first.Body.String(), `"outcome":"succeeded"`) ||
		!strings.Contains(first.Body.String(), `"itemCount":2`) {
		t.Fatalf("first digest = %d %s", first.Code, first.Body.String())
	}
	requireCanonicalTaskResponse(t, first.Body.Bytes())
	reopened := newDigestStore(app.store.path).snapshot()
	if reopened.LastRun == nil ||
		reopened.LastRun.OccurrenceID != "digest:2026-11-03" ||
		reopened.LastRun.ItemCount != 2 {
		t.Fatalf("persisted digest state = %+v", reopened)
	}
	second := run(body, identity)
	if second.Code != http.StatusOK ||
		!strings.Contains(second.Body.String(), `"duplicate":true`) {
		t.Fatalf("duplicate digest = %d %s", second.Code, second.Body.String())
	}
	changed := run(
		taskBody(t, `{"scheduleId":"daily","reportIds":[41]}`), identity)
	if !strings.Contains(changed.Body.String(), `"error_code":"digest_identity_conflict"`) {
		t.Fatalf("changed digest identity = %s", changed.Body.String())
	}
	requireCanonicalTaskResponse(t, changed.Body.Bytes())
	denied := run(body, testIdentity([]string{"tasks.schedule"}, now))
	if !strings.Contains(denied.Body.String(), `"error_code":"digest_authority_invalid"`) {
		t.Fatalf("missing report authority = %s", denied.Body.String())
	}
}

func TestDigestStatusAndReadiness(t *testing.T) {
	app, _ := testApplication(t)
	health := httptest.NewRecorder()
	app.ServeHTTP(
		health,
		httptest.NewRequest(
			http.MethodGet, "http://portal-app.invalid/health/ready", nil))
	if health.Code != http.StatusOK ||
		!strings.Contains(health.Body.String(), `"ready":true`) {
		t.Fatalf("health = %d %s", health.Code, health.Body.String())
	}
	status := httptest.NewRecorder()
	app.ServeHTTP(
		status,
		httptest.NewRequest(
			http.MethodGet, "http://portal-app.invalid/v1/digest", nil))
	if status.Code != http.StatusOK ||
		!strings.Contains(status.Body.String(), `"format":"scheduled-digest.state/1-dev.1"`) ||
		!strings.Contains(status.Body.String(), `"lastRun":null`) {
		t.Fatalf("status = %d %s", status.Code, status.Body.String())
	}
}

func TestHandshakeBindsRegistrationKeyAndBoot(t *testing.T) {
	app, registration := testApplication(t)
	defer clear(registration.Key)
	signer, err := registration.signer(app.bootID)
	if err != nil {
		t.Fatal(err)
	}
	defer clear(signer.Key)
	challenge, err := signer.NewChallenge(time.Now())
	if err != nil {
		t.Fatal(err)
	}
	body, _ := json.Marshal(map[string]string{"challenge": challenge})
	request := httptest.NewRequest(
		http.MethodPost, "http://portal-app.invalid/v1/handshake",
		bytes.NewReader(body))
	request.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	app.ServeHTTP(recorder, request)
	if recorder.Code != http.StatusOK {
		t.Fatalf("handshake = %d %s", recorder.Code, recorder.Body.String())
	}
	var response struct {
		Answer string `json:"answer"`
	}
	if strictJSON(recorder.Body.Bytes(), &response) != nil ||
		response.Answer == "" {
		t.Fatalf("handshake answer = %s", recorder.Body.String())
	}
	bootID, err := signer.VerifyAnswer(challenge, response.Answer, time.Now())
	if err != nil || bootID != app.bootID {
		t.Fatalf("handshake boot = %q, %v", bootID, err)
	}

	wrong := signer
	wrong.Key = bytes.Clone(signer.Key)
	defer clear(wrong.Key)
	wrong.Key[0] ^= 1
	wrongChallenge, err := wrong.NewChallenge(time.Now())
	if err != nil {
		t.Fatal(err)
	}
	wrongBody, _ := json.Marshal(map[string]string{"challenge": wrongChallenge})
	wrongRequest := httptest.NewRequest(
		http.MethodPost, "http://portal-app.invalid/v1/handshake",
		bytes.NewReader(wrongBody))
	wrongRequest.Header.Set("Content-Type", "application/json")
	wrongRecorder := httptest.NewRecorder()
	app.ServeHTTP(wrongRecorder, wrongRequest)
	if wrongRecorder.Code != http.StatusBadRequest {
		t.Fatalf("wrong-key handshake = %d %s",
			wrongRecorder.Code, wrongRecorder.Body.String())
	}
}

func TestHandshakeRefusesChangedRegistrationAndRequestAuthority(t *testing.T) {
	app, registration := testApplication(t)
	defer clear(registration.Key)
	path := app.registration
	changed := registration
	changed.Key = bytes.Clone(registration.Key)
	defer clear(changed.Key)
	changed.Key[0] ^= 1
	raw, err := json.Marshal(changed)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	signer, err := registration.signer(app.bootID)
	if err != nil {
		t.Fatal(err)
	}
	defer clear(signer.Key)
	challenge, err := signer.NewChallenge(time.Now())
	if err != nil {
		t.Fatal(err)
	}
	body, _ := json.Marshal(map[string]string{"challenge": challenge})
	request := httptest.NewRequest(
		http.MethodPost, "http://portal-app.invalid/v1/handshake",
		bytes.NewReader(body))
	request.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	app.ServeHTTP(recorder, request)
	if recorder.Code != http.StatusServiceUnavailable {
		t.Fatalf("changed registration handshake = %d %s",
			recorder.Code, recorder.Body.String())
	}
	if err := os.WriteFile(
		path, mustRegistrationJSON(t, registration), 0600); err != nil {
		t.Fatal(err)
	}
	for name, mutate := range map[string]func(*http.Request){
		"query": func(r *http.Request) {
			r.URL.RawQuery = "redirect=https://example.invalid"
		},
		"cookie": func(r *http.Request) {
			r.Header.Set("Cookie", "session=private")
		},
		"authorization": func(r *http.Request) {
			r.Header.Set("Authorization", "Bearer private")
		},
		"content type": func(r *http.Request) {
			r.Header.Set("Content-Type", "text/plain")
		},
		"unknown field": func(r *http.Request) {
			r.Body = io.NopCloser(
				bytes.NewReader(
					[]byte(`{"challenge":"a.b","redirect":"private"}`)))
		},
		"invalid challenge": func(r *http.Request) {
			r.Body = io.NopCloser(
				bytes.NewReader([]byte(`{"challenge":"private"}`)))
		},
	} {
		t.Run(name, func(t *testing.T) {
			body, _ := json.Marshal(map[string]string{"challenge": challenge})
			request := httptest.NewRequest(
				http.MethodPost, "http://portal-app.invalid/v1/handshake",
				bytes.NewReader(body))
			request.Header.Set("Content-Type", "application/json")
			mutate(request)
			recorder := httptest.NewRecorder()
			app.ServeHTTP(recorder, request)
			if recorder.Code != http.StatusBadRequest {
				t.Fatalf("refused handshake = %d %s",
					recorder.Code, recorder.Body.String())
			}
		})
	}
}

func TestScheduledDigestOnlyRoutesFixedDigestTask(t *testing.T) {
	app, _ := testApplication(t)
	for _, path := range []string{
		"/v1/tasks/run", "/v1/tasks/digest/other", "/v1/events/subscribe",
	} {
		request := httptest.NewRequest(
			http.MethodPost, "http://portal-app.invalid"+path,
			bytes.NewReader([]byte(`{}`)))
		request.Header.Set("Content-Type", "application/json")
		recorder := httptest.NewRecorder()
		app.ServeHTTP(recorder, request)
		if recorder.Code != http.StatusNotFound {
			t.Fatalf("unexpected route %s = %d %s",
				path, recorder.Code, recorder.Body.String())
		}
	}
	request := httptest.NewRequest(
		http.MethodGet, "http://portal-app.invalid/v1/handshake", nil)
	recorder := httptest.NewRecorder()
	app.ServeHTTP(recorder, request)
	if recorder.Code != http.StatusNotFound {
		t.Fatalf("GET handshake = %d %s", recorder.Code, recorder.Body.String())
	}
}

func mustRegistrationJSON(t *testing.T, registration backendRegistration) []byte {
	t.Helper()
	raw, err := json.Marshal(registration)
	if err != nil {
		t.Fatal(err)
	}
	return raw
}

func requireCanonicalTaskResponse(t *testing.T, raw []byte) {
	t.Helper()
	var response taskResponse
	if strictJSON(raw, &response) != nil {
		t.Fatalf("task response is not closed JSON: %s", raw)
	}
	canonical, err := json.Marshal(response)
	if err != nil || !bytes.Equal(canonical, raw) {
		t.Fatalf("task response is not canonical: %s", raw)
	}
}
