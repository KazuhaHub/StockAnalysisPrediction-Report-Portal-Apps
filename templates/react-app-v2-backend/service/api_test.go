package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

const (
	testInstallation = "10000000-0000-4000-8000-000000000001"
	testTaskID       = "10000000-0000-4000-8000-000000000002"
	testLeaseID      = "10000000-0000-4000-8000-000000000003"
	testEpoch        = "10000000-0000-4000-8000-000000000004"
	testRelease      = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	testBoot         = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
)

func testRegistration() backendRegistration {
	key := bytes.Repeat([]byte{0x23}, 32)
	sum := sha256.Sum256(key)
	var r backendRegistration
	r.Format = backendRegistrationFmt
	r.Metadata.Identity.AppID = applicationID
	r.Metadata.Identity.DeploymentID = "10000000-0000-4000-8000-000000000005"
	r.Metadata.Identity.ControllerEpoch = testEpoch
	r.Metadata.Identity.InstallationID = testInstallation
	r.Metadata.Identity.Generation = "1"
	r.Metadata.Identity.PolicyRevision = "1"
	r.Metadata.Identity.ReleaseSHA256 = testRelease
	r.Metadata.InstanceID = strings.Repeat("d", 64)
	r.Metadata.KeyID = hex.EncodeToString(sum[:])
	r.Key = key
	return r
}

type testEnv struct {
	srv    *server
	signer protocol.Signer
	queue  *Queue
}

func newTestEnv(t *testing.T) testEnv {
	t.Helper()
	root := t.TempDir()
	reg := testRegistration()
	raw, err := json.Marshal(reg)
	if err != nil {
		t.Fatal(err)
	}
	regPath := filepath.Join(root, "registration.json")
	if err := os.WriteFile(regPath, raw, 0600); err != nil {
		t.Fatal(err)
	}
	queue, err := NewQueue(filepath.Join(root, "data"), jobs)
	if err != nil {
		t.Fatal(err)
	}
	signer, err := reg.signer(testBoot)
	if err != nil {
		t.Fatal(err)
	}
	return testEnv{srv: newServer(queue, newAuthority(regPath, testBoot)), signer: signer, queue: queue}
}

func (e testEnv) get(t *testing.T, path string, signed bool, headers ...string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(http.MethodGet, "http://portal-app.invalid"+path, nil)
	if signed {
		token, err := e.signer.Sign(http.MethodGet, path, nil,
			protocol.Viewer{Subject: "u1", Role: "reader", OUs: []string{"ou1"}}, time.Now())
		if err != nil {
			t.Fatal(err)
		}
		req.Header.Set("X-Portal-Assertion", token)
	}
	for i := 0; i+1 < len(headers); i += 2 {
		req.Header.Set(headers[i], headers[i+1])
	}
	rec := httptest.NewRecorder()
	e.srv.ServeHTTP(rec, req)
	return rec
}

func decode(t *testing.T, rec *httptest.ResponseRecorder) map[string]any {
	t.Helper()
	var out map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
		t.Fatalf("body %q: %v", rec.Body.String(), err)
	}
	return out
}

func TestReadinessNeedsNoViewer(t *testing.T) {
	e := newTestEnv(t)
	rec := e.get(t, "/health/ready", false)
	if rec.Code != http.StatusOK || decode(t, rec)["protocol"] != "portal.backend/1" {
		t.Fatalf("%d %s", rec.Code, rec.Body)
	}
	if rec := e.get(t, "/health/ready?x=1", false); rec.Code != http.StatusBadRequest {
		t.Fatalf("query accepted: %d", rec.Code)
	}
}

func TestHelloReturnsTheVerifiedViewersRole(t *testing.T) {
	e := newTestEnv(t)
	rec := e.get(t, "/v1/hello", true)
	out := decode(t, rec)
	if rec.Code != http.StatusOK || out["greeting"] != "hello" || out["role"] != "reader" {
		t.Fatalf("%d %v", rec.Code, out)
	}
	if rec.Header().Get("Content-Type") != "application/json" {
		t.Fatalf("content type %q", rec.Header().Get("Content-Type"))
	}
}

func TestViewerRoutesRequireAValidAssertion(t *testing.T) {
	e := newTestEnv(t)
	if rec := e.get(t, "/v1/hello", false); rec.Code != http.StatusForbidden {
		t.Fatalf("unsigned: %d", rec.Code)
	}
	// A token is bound to its request URI: one signed for another path is refused.
	other, _ := e.signer.Sign(http.MethodGet, "/v1/other", nil, protocol.Viewer{Subject: "u1", Role: "reader"}, time.Now())
	if rec := e.get(t, "/v1/hello", false, "X-Portal-Assertion", other); rec.Code != http.StatusForbidden {
		t.Fatalf("wrong path: %d", rec.Code)
	}
	// ... and to this boot: a token for another boot ID is refused.
	old := e.signer
	old.BootID = "cccccccccccccccccccccccccccccccc"
	stale, _ := old.Sign(http.MethodGet, "/v1/hello", nil, protocol.Viewer{Subject: "u1", Role: "reader"}, time.Now())
	if rec := e.get(t, "/v1/hello", false, "X-Portal-Assertion", stale); rec.Code != http.StatusForbidden {
		t.Fatalf("old boot: %d", rec.Code)
	}
	// A token works once.
	token, _ := e.signer.Sign(http.MethodGet, "/v1/hello", nil, protocol.Viewer{Subject: "u1", Role: "reader"}, time.Now())
	if rec := e.get(t, "/v1/hello", false, "X-Portal-Assertion", token); rec.Code != http.StatusOK {
		t.Fatalf("first use: %d", rec.Code)
	}
	if rec := e.get(t, "/v1/hello", false, "X-Portal-Assertion", token); rec.Code != http.StatusForbidden {
		t.Fatalf("replay: %d", rec.Code)
	}
}

func TestViewerRoutesRefuseAmbientCredentials(t *testing.T) {
	e := newTestEnv(t)
	for _, header := range []string{"Cookie", "Authorization"} {
		if rec := e.get(t, "/v1/hello", true, header, "x"); rec.Code != http.StatusBadRequest {
			t.Errorf("%s accepted: %d", header, rec.Code)
		}
	}
}

func TestReservedRouteSpacesAreNeverServedAsViewerRoutes(t *testing.T) {
	e := newTestEnv(t)
	for _, space := range reservedSpaces {
		// Even a perfectly valid viewer assertion does not open these spaces.
		if rec := e.get(t, space+"x", true); rec.Code != http.StatusNotFound {
			t.Errorf("%sx: %d", space, rec.Code)
		}
	}
}

func TestHandshakeProvesTheRegistrationKey(t *testing.T) {
	e := newTestEnv(t)
	host := e.signer
	host.BootID = ""
	challenge, err := host.NewChallenge(time.Now())
	if err != nil {
		t.Fatal(err)
	}
	body, _ := json.Marshal(map[string]string{"challenge": challenge})
	req := httptest.NewRequest(http.MethodPost, "http://portal-app.invalid/v1/handshake", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	e.srv.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("%d %s", rec.Code, rec.Body)
	}
	boot, err := host.VerifyAnswer(challenge, decode(t, rec)["answer"].(string), time.Now())
	if err != nil || boot != testBoot {
		t.Fatalf("boot %q err %v", boot, err)
	}
	bad := httptest.NewRequest(http.MethodPost, "http://portal-app.invalid/v1/handshake", strings.NewReader("{}"))
	bad.Header.Set("Content-Type", "application/json")
	badRec := httptest.NewRecorder()
	e.srv.ServeHTTP(badRec, bad)
	if badRec.Code != http.StatusBadRequest || badRec.Header().Get("Content-Type") != "application/json" {
		t.Fatalf("%d %q", badRec.Code, badRec.Header().Get("Content-Type"))
	}
}

func serviceIdentityHeader(resources []string, now time.Time) string {
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

func (e testEnv) task(t *testing.T, occurrence, payload, identity string, headers ...string) map[string]any {
	t.Helper()
	body, _ := json.Marshal(taskRequest{Format: taskRequestFormat, TaskID: testTaskID,
		OccurrenceID: occurrence, Payload: json.RawMessage(payload)})
	req := httptest.NewRequest(http.MethodPost, "http://portal-app.invalid/v1/tasks/run", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Portal-Service-Identity", identity)
	for i := 0; i+1 < len(headers); i += 2 {
		req.Header.Set(headers[i], headers[i+1])
	}
	rec := httptest.NewRecorder()
	e.srv.ServeHTTP(rec, req)
	if rec.Code != 200 {
		t.Fatalf("task http %d", rec.Code)
	}
	return decode(t, rec)
}

func TestTaskOnlyEnqueuesAndIsIdempotent(t *testing.T) {
	e := newTestEnv(t)
	id := serviceIdentityHeader([]string{"tasks.schedule"}, time.Now())
	started := time.Now()
	first := e.task(t, "run:1", `{"job":"example"}`, id)
	if first["outcome"] != "succeeded" || first["result"].(map[string]any)["duplicate"] != false {
		t.Fatalf("first %v", first)
	}
	// The worker has not been started: the answer came from accepting the work, not doing it.
	if len(e.queue.waiting) != 1 || time.Since(started) > time.Second {
		t.Fatalf("waiting %d after %s", len(e.queue.waiting), time.Since(started))
	}
	second := e.task(t, "run:1", `{"job":"example"}`, id)
	if second["result"].(map[string]any)["duplicate"] != true || len(e.queue.waiting) != 1 {
		t.Fatalf("duplicate %v (pending %d)", second, len(e.queue.waiting))
	}
}

func TestTaskRefusesBadAuthorityAndPayloads(t *testing.T) {
	e := newTestEnv(t)
	now := time.Now()
	if out := e.task(t, "run:1", `{"job":"example"}`, serviceIdentityHeader([]string{"reports.read"}, now)); out["error_code"] != "run_authority_invalid" {
		t.Fatalf("missing tasks.schedule: %v", out)
	}
	ok := serviceIdentityHeader([]string{"tasks.schedule"}, now)
	if out := e.task(t, "run:1", `{"job":"example"}`, ok, "X-Portal-Assertion", "x"); out["error_code"] != "run_request_invalid" {
		t.Fatalf("viewer assertion on a task: %v", out)
	}
	var wrongEpoch serviceIdentity
	_ = json.Unmarshal([]byte(ok), &wrongEpoch)
	wrongEpoch.ControllerEpoch = "10000000-0000-4000-8000-0000000000ff"
	raw, _ := json.Marshal(wrongEpoch)
	if out := e.task(t, "run:1", `{"job":"example"}`, string(raw)); out["error_code"] != "run_authority_invalid" {
		t.Fatalf("wrong epoch accepted: %v", out)
	}
	for _, payload := range []string{`{"job":"unknown"}`, `{"job":"example","extra":1}`, `{}`, `[]`} {
		if out := e.task(t, "run:1", payload, ok); out["outcome"] != "failed" {
			t.Errorf("%s accepted: %v", payload, out)
		}
	}
	if len(e.queue.waiting) != 0 {
		t.Fatalf("a refused task was queued")
	}
}

// devClientRegistration is the exact file packages/extensionprotocol/cmd/portal-dev-client
// writes for the app "demo" (scripts/run-backend-local.py uses it). The service must
// accept it, or a local run could not hand-shake with the dev client.
const devClientRegistration = `{"format":"portal.managed-backend-registration/1-dev.1","metadata":{"identity":{"app_id":"demo","deployment_id":"portal-dev-local","controller_epoch":"00000000-0000-4000-8000-000000000d02","installation_id":"00000000-0000-4000-8000-000000000d01","generation":"1","policy_revision":"1","release_sha256":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"},"instance_id":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee","key_id":"5b19d45be03b87bdee0a7323ec312e8a11c89e91210d0cbe041e183ec111840f"},"signing_key":"IyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyM="}`

func TestTheLocalDevClientsRegistrationLoads(t *testing.T) {
	raw := strings.Replace(devClientRegistration, `"app_id":"demo"`, `"app_id":"`+applicationID+`"`, 1)
	path := filepath.Join(t.TempDir(), "registration.json")
	if err := os.WriteFile(path, []byte(raw), 0600); err != nil {
		t.Fatal(err)
	}
	reg, err := loadRegistration(path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := reg.signer(testBoot); err != nil {
		t.Fatal(err)
	}
}

func TestAFullQueueAsksPortalToRetryInsteadOfFailingTheTask(t *testing.T) {
	e := newTestEnv(t)
	id := serviceIdentityHeader([]string{"tasks.schedule"}, time.Now())
	for i := 0; i < queueCapacity; i++ {
		if out := e.task(t, "run:"+strconv.Itoa(i), `{"job":"example"}`, id); out["outcome"] != "succeeded" {
			t.Fatalf("%d: %v", i, out)
		}
	}
	out := e.task(t, "run:overflow", `{"job":"example"}`, id)
	if out["outcome"] != "retry" || out["error_code"] != "run_queue_full" {
		t.Fatalf("overflow: %v", out)
	}
	// A repeated occurrence is a duplicate of accepted work, not a failure.
	if out := e.task(t, "run:0", `{"job":"example"}`, id); out["result"].(map[string]any)["duplicate"] != true {
		t.Fatalf("known occurrence: %v", out)
	}
}
