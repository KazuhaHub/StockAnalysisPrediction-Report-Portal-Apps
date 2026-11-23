package main

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

const manualRequest = "20000000-0000-4000-8000-000000000001"

var adminViewer = protocol.Viewer{Subject: "a1", Role: "admin"}

// call sends a request signed as a reader ("reader"), an admin view ("admin")
// or not at all ("").
func (e testEnv) call(t *testing.T, method, path, body, as string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(method, "http://portal-app.invalid"+path, strings.NewReader(body))
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	var token string
	var err error
	switch as {
	case "reader":
		token, err = e.signer.Sign(method, path, []byte(body), protocol.Viewer{Subject: "u1", Role: "reader"}, time.Now())
	case "admin":
		token, err = e.signer.SignAdmin(method, path, []byte(body), adminViewer, time.Now())
	}
	if err != nil {
		t.Fatal(err)
	}
	if token != "" {
		req.Header.Set("X-Portal-Assertion", token)
	}
	rec := httptest.NewRecorder()
	e.srv.ServeHTTP(rec, req)
	return rec
}

func runNowBody(id string) string { return `{"request_id":"` + id + `"}` }

func TestAdminRoutesRefuseEveryoneButAdminViews(t *testing.T) {
	e := newTestEnv(t)
	run, _, err := e.srv.runner.Submit("margin", "task", "occ")
	if err != nil {
		t.Fatal(err)
	}
	cases := [][2]string{
		{http.MethodGet, "/v1/admin/jobs"},
		{http.MethodGet, "/v1/admin/runs"},
		{http.MethodGet, "/v1/admin/runs/" + run.ID + "/log"},
		{http.MethodPost, "/v1/admin/jobs/margin/run"},
	}
	for _, c := range cases {
		body := ""
		if c[0] == http.MethodPost {
			body = runNowBody(manualRequest)
		}
		for _, as := range []string{"", "reader"} {
			rec := e.call(t, c[0], c[1], body, as)
			if rec.Code != http.StatusForbidden || !strings.Contains(rec.Body.String(), "forbidden") {
				t.Errorf("%s %s as %q: %d %s", c[0], c[1], as, rec.Code, rec.Body.String())
			}
		}
	}
	if n := len(e.srv.runner.Runs()); n != 1 {
		t.Fatalf("a refused request queued a run: %d runs", n)
	}
	for _, c := range cases[:3] {
		if rec := e.call(t, c[0], c[1], "", "admin"); rec.Code != http.StatusOK {
			t.Errorf("%s admin: %d %s", c[1], rec.Code, rec.Body.String())
		}
	}
}

func TestAdminAssertionMayReadReaderRoutes(t *testing.T) {
	e := newTestEnv(t)
	if rec := e.call(t, http.MethodGet, "/v1/margin/summary", "", "admin"); rec.Code != http.StatusOK {
		t.Fatalf("%d %s", rec.Code, rec.Body.String())
	}
	if rec := e.call(t, http.MethodGet, "/v1/margin/summary", "", "reader"); rec.Code != http.StatusOK {
		t.Fatalf("reader %d", rec.Code)
	}
}

func TestReaderRunsRouteIsGone(t *testing.T) {
	e := newTestEnv(t)
	for _, as := range []string{"reader", "admin"} {
		if rec := e.call(t, http.MethodGet, "/v1/runs", "", as); rec.Code != http.StatusNotFound {
			t.Errorf("%s: %d %s", as, rec.Code, rec.Body.String())
		}
	}
}

func TestAdminJobsListScheduleNextAndLastRun(t *testing.T) {
	e := newTestEnv(t)
	now := at(time.Monday, 9, 20)
	e.srv.now = func() time.Time { return now }
	run, _, _ := e.srv.runner.Submit("margin", "manual/x", "manual:x")
	e.srv.runner.update(run.ID, func(r *Run) { r.Status, r.Error = "failed", "exit_status" })
	out := decode(t, e.call(t, http.MethodGet, "/v1/admin/jobs", "", "admin"))
	if out["time_zone"] != "Asia/Shanghai" {
		t.Fatalf("zone %v", out["time_zone"])
	}
	jobs := out["jobs"].([]any)
	if len(jobs) != 1 {
		t.Fatalf("jobs %v", jobs)
	}
	job := jobs[0].(map[string]any)
	slots := job["schedule"].([]any)
	if job["name"] != "margin" || len(slots) != 2 {
		t.Fatalf("job %v", job)
	}
	first := slots[0].(map[string]any)
	if first["hour"] != float64(9) || first["minute"] != float64(0) || first["fallback"] != false || len(first["days"].([]any)) != 5 {
		t.Fatalf("slot %v", first)
	}
	if slots[1].(map[string]any)["fallback"] != true {
		t.Fatalf("fallback slot %v", slots[1])
	}
	if want := at(time.Monday, 9, 50).Format(time.RFC3339); job["next_run"] != want {
		t.Fatalf("next %v want %s", job["next_run"], want)
	}
	last := job["last_run"].(map[string]any)
	if last["status"] != "failed" || last["error"] != "exit_status" || last["source"] != "manual" {
		t.Fatalf("last %v", last)
	}
}

func TestSlotNextSkipsToTheNextRunDay(t *testing.T) {
	sl := Slot{Job: "margin", Days: weekdays, Hour: 9}
	got, ok := sl.next(at(time.Friday, 9, 0), shanghai)
	if !ok || !got.Equal(at(time.Monday, 9, 0).AddDate(0, 0, 7)) {
		t.Fatalf("next after Friday 09:00: %v %v", got, ok)
	}
}

func TestAdminRunsCarryTheSource(t *testing.T) {
	e := newTestEnv(t)
	e.srv.runner.Submit("margin", "schedule/margin/2026-11-16T09:00", "run:2026-11-16T09:00")
	e.srv.runner.Submit("margin", "platform-task", "run:abc")
	e.call(t, http.MethodPost, "/v1/admin/jobs/margin/run", runNowBody(manualRequest), "admin")
	out := decode(t, e.call(t, http.MethodGet, "/v1/admin/runs", "", "admin"))
	var sources []string
	for _, r := range out["runs"].([]any) {
		m := r.(map[string]any)
		sources = append(sources, m["source"].(string))
		if _, leaked := m["task_id"]; leaked {
			t.Fatalf("task id leaked: %v", m)
		}
	}
	if strings.Join(sources, ",") != "manual,platform,schedule" {
		t.Fatalf("sources %v", sources)
	}
}

func TestAdminRunLogIsATailAndSaysWhenTruncated(t *testing.T) {
	e := newTestEnv(t)
	run, _, _ := e.srv.runner.Submit("margin", "task", "occ")
	path := filepath.Join(e.data, "runs", run.ID+".log")
	logPath := "/v1/admin/runs/" + run.ID + "/log"
	out := decode(t, e.call(t, http.MethodGet, logPath, "", "admin"))
	if out["log"] != "" || out["truncated"] != false {
		t.Fatalf("no log yet: %v", out)
	}
	if err := os.WriteFile(path, []byte("small log"), 0600); err != nil {
		t.Fatal(err)
	}
	out = decode(t, e.call(t, http.MethodGet, logPath, "", "admin"))
	if out["log"] != "small log" || out["truncated"] != false {
		t.Fatalf("small: %v", out)
	}
	big := strings.Repeat("a", maxAdminLogBytes) + "TAIL"
	if err := os.WriteFile(path, []byte(big), 0600); err != nil {
		t.Fatal(err)
	}
	out = decode(t, e.call(t, http.MethodGet, logPath, "", "admin"))
	text := out["log"].(string)
	if out["truncated"] != true || len(text) != maxAdminLogBytes || !strings.HasSuffix(text, "TAIL") {
		t.Fatalf("big: truncated=%v len=%d", out["truncated"], len(text))
	}
	if rec := e.call(t, http.MethodGet, "/v1/admin/runs/made-up/log", "", "admin"); rec.Code != http.StatusNotFound {
		t.Fatalf("made-up id: %d", rec.Code)
	}
	if rec := e.call(t, http.MethodGet, "/v1/admin/runs/nope/log", "", "admin"); rec.Code != http.StatusNotFound {
		t.Fatalf("unknown run: %d", rec.Code)
	}
}

func TestRunNowIsIdempotentPerRequestID(t *testing.T) {
	e := newTestEnv(t)
	first := e.call(t, http.MethodPost, "/v1/admin/jobs/margin/run", runNowBody(manualRequest), "admin")
	if first.Code != http.StatusAccepted {
		t.Fatalf("%d %s", first.Code, first.Body.String())
	}
	a := decode(t, first)
	if a["duplicate"] != false || a["run"].(map[string]any)["status"] != "queued" || a["run"].(map[string]any)["source"] != "manual" {
		t.Fatalf("first %v", a)
	}
	b := decode(t, e.call(t, http.MethodPost, "/v1/admin/jobs/margin/run", runNowBody(manualRequest), "admin"))
	if b["duplicate"] != true || b["run"].(map[string]any)["id"] != a["run"].(map[string]any)["id"] {
		t.Fatalf("second %v", b)
	}
	if n := len(e.srv.runner.Runs()); n != 1 {
		t.Fatalf("%d runs", n)
	}
	c := decode(t, e.call(t, http.MethodPost, "/v1/admin/jobs/margin/run", runNowBody("20000000-0000-4000-8000-000000000002"), "admin"))
	if c["duplicate"] != false || len(e.srv.runner.Runs()) != 2 {
		t.Fatalf("new request id: %v", c)
	}
}

func TestRunNowRefusesBadRequests(t *testing.T) {
	e := newTestEnv(t)
	for name, body := range map[string]string{
		"empty":      "",
		"no id":      `{}`,
		"not a uuid": `{"request_id":"abc"}`,
		"extra key":  `{"request_id":"` + manualRequest + `","x":1}`,
		"trailing":   runNowBody(manualRequest) + `{}`,
		"oversize":   `{"request_id":"` + strings.Repeat("a", 600) + `"}`,
	} {
		if rec := e.call(t, http.MethodPost, "/v1/admin/jobs/margin/run", body, "admin"); rec.Code != http.StatusBadRequest {
			t.Errorf("%s: %d %s", name, rec.Code, rec.Body.String())
		}
	}
	if rec := e.call(t, http.MethodPost, "/v1/admin/jobs/etf/run", runNowBody(manualRequest), "admin"); rec.Code != http.StatusNotFound {
		t.Errorf("unknown job: %d", rec.Code)
	}
	if rec := e.call(t, http.MethodPost, "/v1/admin/jobs/margin/stop", runNowBody(manualRequest), "admin"); rec.Code != http.StatusBadRequest {
		t.Errorf("bad action: %d", rec.Code)
	}
	if n := len(e.srv.runner.Runs()); n != 0 {
		t.Fatalf("%d runs queued by refused requests", n)
	}
}

func TestRunNowRefusesAFullQueue(t *testing.T) {
	e := newTestEnv(t)
	for i := 0; i < maxQueue; i++ {
		if _, _, err := e.srv.runner.Submit("margin", "t"+strings.Repeat("x", i), "o"); err != nil {
			t.Fatal(err)
		}
	}
	rec := e.call(t, http.MethodPost, "/v1/admin/jobs/margin/run", runNowBody(manualRequest), "admin")
	if rec.Code != http.StatusConflict || !strings.Contains(rec.Body.String(), "queue_full") {
		t.Fatalf("%d %s", rec.Code, rec.Body.String())
	}
}

func TestRunSourceNamesWhoStartedARun(t *testing.T) {
	for taskID, want := range map[string]string{
		"schedule/margin/2026-11-23T09:00":            "schedule",
		"manual/20000000-0000-4000-8000-000000000001": "manual",
		"bootstrap/margin/2026-11-23":                 "bootstrap",
		"platform-task-1":                             "platform",
	} {
		if got := runSource(Run{TaskID: taskID}); got != want {
			t.Errorf("runSource(%q) = %q, want %q", taskID, got, want)
		}
	}
}
