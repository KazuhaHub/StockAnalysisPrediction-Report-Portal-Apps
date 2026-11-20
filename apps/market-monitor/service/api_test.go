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
	data   string
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
	data := filepath.Join(root, "data")
	store := NewStore(data)
	if _, err := store.Install("margin", testSnapshot("margin", "2026-11-18")); err != nil {
		t.Fatal(err)
	}
	if _, err := store.Install("margin", testSnapshot("margin", "2026-11-17")); err != nil {
		t.Fatal(err)
	}
	runner, err := NewRunner(data, []JobSpec{{Name: "margin", Command: []string{"/bin/true"}, Timeout: time.Second}}, store)
	if err != nil {
		t.Fatal(err)
	}
	signer, err := reg.signer(testBoot)
	if err != nil {
		t.Fatal(err)
	}
	return testEnv{srv: newServer(store, runner, newAuthority(regPath, testBoot)), signer: signer, data: data}
}

func (e testEnv) get(t *testing.T, path string, signed bool) *httptest.ResponseRecorder {
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

func TestHandshakeErrorsAreJSON(t *testing.T) {
	e := newTestEnv(t)
	req := httptest.NewRequest(http.MethodPost, "http://portal-app.invalid/v1/handshake", strings.NewReader("{}"))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	e.srv.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest || rec.Header().Get("Content-Type") != "application/json" {
		t.Fatalf("%d %q", rec.Code, rec.Header().Get("Content-Type"))
	}
}

func TestReadinessNeedsNoViewer(t *testing.T) {
	e := newTestEnv(t)
	req := httptest.NewRequest(http.MethodGet, "http://portal-app.invalid/health/ready", nil)
	rec := httptest.NewRecorder()
	e.srv.ServeHTTP(rec, req)
	if rec.Code != 200 || !strings.Contains(rec.Body.String(), `"ready":true`) {
		t.Fatalf("%d %s", rec.Code, rec.Body.String())
	}
}

func TestViewerRoutesRequireAValidAssertion(t *testing.T) {
	e := newTestEnv(t)
	if rec := e.get(t, "/v1/margin/summary", false); rec.Code != http.StatusForbidden {
		t.Fatalf("unsigned: %d", rec.Code)
	}
	path := "/v1/margin/summary"
	token, _ := e.signer.Sign(http.MethodGet, path, nil, protocol.Viewer{Subject: "u1", Role: "reader"}, time.Now())
	send := func(p string) int {
		req := httptest.NewRequest(http.MethodGet, "http://portal-app.invalid"+p, nil)
		req.Header.Set("X-Portal-Assertion", token)
		rec := httptest.NewRecorder()
		e.srv.ServeHTTP(rec, req)
		return rec.Code
	}
	if code := send(path + "?date=2026-11-17"); code != http.StatusForbidden {
		t.Fatalf("assertion for another path accepted: %d", code)
	}
	if code := send(path); code != http.StatusOK {
		t.Fatalf("valid assertion refused: %d", code)
	}
	if code := send(path); code != http.StatusForbidden {
		t.Fatalf("replayed assertion accepted: %d", code)
	}
	other := e.signer
	other.BootID = strings.Repeat("c", 32)
	stale, _ := other.Sign(http.MethodGet, path, nil, protocol.Viewer{Subject: "u1", Role: "reader"}, time.Now())
	req := httptest.NewRequest(http.MethodGet, "http://portal-app.invalid"+path, nil)
	req.Header.Set("X-Portal-Assertion", stale)
	rec := httptest.NewRecorder()
	e.srv.ServeHTTP(rec, req)
	if rec.Code != http.StatusForbidden {
		t.Fatalf("old boot accepted: %d", rec.Code)
	}
}

func TestViewerRoutesRefuseAmbientCredentials(t *testing.T) {
	e := newTestEnv(t)
	path := "/v1/margin/summary"
	token, _ := e.signer.Sign(http.MethodGet, path, nil, protocol.Viewer{Subject: "u1", Role: "reader"}, time.Now())
	req := httptest.NewRequest(http.MethodGet, "http://portal-app.invalid"+path, nil)
	req.Header.Set("X-Portal-Assertion", token)
	req.Header.Set("Cookie", "rp_session=x")
	rec := httptest.NewRecorder()
	e.srv.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("cookie accepted: %d", rec.Code)
	}
}

func TestErrorsAreJSONWithRelayStatuses(t *testing.T) {
	e := newTestEnv(t)
	allowed := map[int]bool{400: true, 403: true, 404: true, 409: true, 422: true, 429: true}
	for _, c := range []struct {
		path   string
		signed bool
		code   string
	}{
		{"/v1/margin/summary", false, "forbidden"},
		{"/v1/etf/summary", true, "no_data"},
		{"/v1/margin/rows/999999", true, "not_found"},
		{"/v1/margin/rows?size=999", true, "bad_request"},
		{"/v1/bogus/summary", true, "not_found"},
	} {
		rec := e.get(t, c.path, c.signed)
		if !allowed[rec.Code] || rec.Header().Get("Content-Type") != "application/json" {
			t.Errorf("%s: %d %q", c.path, rec.Code, rec.Header().Get("Content-Type"))
			continue
		}
		if out := decode(t, rec); out["error"] != c.code {
			t.Errorf("%s: error %v, want %s", c.path, out["error"], c.code)
		}
	}
}

func TestSummaryAndDates(t *testing.T) {
	e := newTestEnv(t)
	out := decode(t, e.get(t, "/v1/margin/summary", true))
	if out["as_of"] != "2026-11-18" || out["summary"].(map[string]any)["n"] != 3.0 {
		t.Fatalf("latest summary %v", out)
	}
	out = decode(t, e.get(t, "/v1/margin/summary?date=2026-11-17", true))
	if out["as_of"] != "2026-11-17" {
		t.Fatalf("dated summary %v", out)
	}
	if _, ok := out["rows"]; ok {
		t.Fatal("summary must not carry rows")
	}
	out = decode(t, e.get(t, "/v1/margin/dates", true))
	if dates := out["dates"].([]any); len(dates) != 2 || dates[0] != "2026-11-18" {
		t.Fatalf("dates %v", out)
	}
	if rec := e.get(t, "/v1/etf/summary", true); rec.Code != http.StatusNotFound {
		t.Fatalf("missing module data: %d", rec.Code)
	}
	if rec := e.get(t, "/v1/bogus/summary", true); rec.Code != http.StatusNotFound {
		t.Fatalf("unknown module: %d", rec.Code)
	}
	if rec := e.get(t, "/v1/margin/summary?date=yesterday", true); rec.Code != http.StatusBadRequest {
		t.Fatalf("bad date: %d", rec.Code)
	}
}

func TestRowsArePagedFilteredAndSorted(t *testing.T) {
	e := newTestEnv(t)
	out := decode(t, e.get(t, "/v1/margin/rows?page=1&size=2&sort=frag&order=desc", true))
	items := out["items"].([]any)
	if out["total"] != 3.0 || len(items) != 2 || items[0].(map[string]any)["code"] != "600000" {
		t.Fatalf("rows %v", out)
	}
	out = decode(t, e.get(t, "/v1/margin/rows?f.state=%E5%AE%89%E5%85%A8", true))
	if out["total"] != 1.0 {
		t.Fatalf("filter %v", out)
	}
	for _, bad := range []string{"?size=500", "?page=0", "?order=sideways", "?sort=bad%20field", "?f.=x", "?unknown=1"} {
		if rec := e.get(t, "/v1/margin/rows"+bad, true); rec.Code != http.StatusBadRequest {
			t.Errorf("%s: %d", bad, rec.Code)
		}
	}
}

func TestRowDetail(t *testing.T) {
	e := newTestEnv(t)
	out := decode(t, e.get(t, "/v1/margin/rows/600000", true))
	if out["row"].(map[string]any)["name"] != "A" || out["detail"] == nil {
		t.Fatalf("detail %v", out)
	}
	out = decode(t, e.get(t, "/v1/margin/rows/000001", true))
	if out["detail"] != nil {
		t.Fatalf("absent detail must be null: %v", out)
	}
	if rec := e.get(t, "/v1/margin/rows/999999", true); rec.Code != http.StatusNotFound {
		t.Fatalf("unknown code: %d", rec.Code)
	}
}

func TestResponsesStayWithinTheRelayLimit(t *testing.T) {
	e := newTestEnv(t)
	big := map[string]any{"code": "600000", "blob": strings.Repeat("x", maxResponse)}
	if _, err := e.srv.store.Install("etf", testSnapshot("etf", "2026-11-18", big)); err != nil {
		t.Fatal(err)
	}
	if rec := e.get(t, "/v1/etf/rows/600000", true); rec.Code != http.StatusUnprocessableEntity {
		t.Fatalf("oversized response: %d", rec.Code)
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

func (e testEnv) task(t *testing.T, payload, identity string, headers ...string) map[string]any {
	t.Helper()
	body, _ := json.Marshal(taskRequest{Format: taskRequestFormat, TaskID: testTaskID,
		OccurrenceID: "run:2026-11-18", Payload: json.RawMessage(payload)})
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

func TestTaskStartsARunAndIsIdempotent(t *testing.T) {
	e := newTestEnv(t)
	id := serviceIdentityHeader([]string{"tasks.schedule"}, time.Now())
	first := e.task(t, `{"job":"margin"}`, id)
	if first["outcome"] != "succeeded" {
		t.Fatalf("first %v", first)
	}
	result := first["result"].(map[string]any)
	if result["status"] != "queued" || result["run_id"] == "" {
		t.Fatalf("result %v", result)
	}
	second := e.task(t, `{"job":"margin"}`, id)
	if r2 := second["result"].(map[string]any); r2["run_id"] != result["run_id"] || r2["duplicate"] != true {
		t.Fatalf("duplicate %v", second)
	}
	rec := e.get(t, "/v1/runs", true)
	out := decode(t, rec)
	if runs := out["runs"].([]any); len(runs) != 1 {
		t.Fatalf("runs %v", out)
	}
	if strings.Contains(rec.Body.String(), testTaskID) {
		t.Fatalf("runs view leaks the platform task id: %s", rec.Body.String())
	}
}

func TestTaskRefusesBadAuthorityAndPayloads(t *testing.T) {
	e := newTestEnv(t)
	now := time.Now()
	if out := e.task(t, `{"job":"margin"}`, serviceIdentityHeader([]string{"reports.read"}, now)); out["error_code"] != "run_authority_invalid" {
		t.Fatalf("missing tasks.schedule: %v", out)
	}
	ok := serviceIdentityHeader([]string{"tasks.schedule"}, now)
	if out := e.task(t, `{"job":"margin"}`, ok, "X-Portal-Assertion", "x"); out["error_code"] != "run_request_invalid" {
		t.Fatalf("viewer assertion on a task: %v", out)
	}
	var wrongEpoch, future serviceIdentity
	_ = json.Unmarshal([]byte(ok), &wrongEpoch)
	_ = json.Unmarshal([]byte(ok), &future)
	wrongEpoch.ControllerEpoch = "10000000-0000-4000-8000-0000000000ff"
	future.IssuedMS = strconv.FormatInt(now.Add(time.Minute).UnixMilli(), 10)
	future.ExpiresMS = strconv.FormatInt(now.Add(2*time.Minute).UnixMilli(), 10)
	for name, g := range map[string]serviceIdentity{"epoch": wrongEpoch, "future": future} {
		raw, _ := json.Marshal(g)
		if out := e.task(t, `{"job":"margin"}`, string(raw)); out["error_code"] != "run_authority_invalid" {
			t.Errorf("%s accepted: %v", name, out)
		}
	}
	for _, payload := range []string{`{"job":"etf"}`, `{"job":"margin","extra":1}`, `{}`, `[]`} {
		if out := e.task(t, payload, ok); out["outcome"] != "failed" {
			t.Errorf("%s accepted: %v", payload, out)
		}
	}
}
