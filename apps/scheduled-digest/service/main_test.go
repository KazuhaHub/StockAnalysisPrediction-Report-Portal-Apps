package main

import (
	"bytes"
	"encoding/json"
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

func testApplication(t *testing.T) application {
	t.Helper()
	root := t.TempDir()
	registration := `{"format":"portal.managed-backend-registration/1-dev.1","metadata":{"identity":{"app_id":"scheduled-digest","installation_id":"` + testInstallation + `","deployment_id":"10000000-0000-4000-8000-000000000005","controller_epoch":"` + testEpoch + `","generation":"1","policy_revision":"1","release_sha256":"` + testRelease + `"},"instance_id":"instance","key_id":"key"},"signing_key":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="}`
	if err := os.WriteFile(
		filepath.Join(root, "registration.json"),
		[]byte(registration), 0600); err != nil {
		t.Fatal(err)
	}
	store := newDigestStore(filepath.Join(root, "state.json"))
	store.now = func() time.Time {
		return time.Date(2026, 11, 3, 23, 0, 0, 0, time.UTC)
	}
	return application{
		store: store, registration: filepath.Join(root, "registration.json"),
	}
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
	app := testApplication(t)
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
	denied := run(body, testIdentity([]string{"tasks.schedule"}, now))
	if !strings.Contains(denied.Body.String(), `"error_code":"digest_authority_invalid"`) {
		t.Fatalf("missing report authority = %s", denied.Body.String())
	}
}

func TestDigestStatusAndReadiness(t *testing.T) {
	app := testApplication(t)
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
