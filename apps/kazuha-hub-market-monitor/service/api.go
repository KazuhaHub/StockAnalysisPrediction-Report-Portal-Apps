package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

// readinessDataFormat is the on-disk format of docs/store-v2.md. It must equal app.v2.json data.schema:
// the runner admits the backend only when the two agree.
const readinessDataFormat = "2"

// Viewer routes (all GET, all require a verified X-Portal-Assertion):
//
//	/v1/{module}/dates               snapshot dates, newest first
//	/v1/{module}/summary?date=       module summary without the row table
//	/v1/{module}/rows?date=&page=&size=&sort=&order=&q=&f.<field>=
//	/v1/{module}/rows/{code}?date=   one row and its detail
//	/v1/{module}/history/dates, history, compare, streak, counts
//	                                 cross-day queries (history_api.go)
//
// Admin routes (the platform signs "surface":"admin" assertions only for an
// app's admin view, after checking that the viewer administers the app; the
// routes below refuse every other assertion with 403 "forbidden"):
//
//	GET  /v1/admin/jobs              jobs, their schedule, next and last run
//	GET  /v1/admin/runs              full run history
//	GET  /v1/admin/runs/{id}/log     bounded tail of one run's log
//	POST /v1/admin/jobs/{job}/run    start a job by hand (admin.go)
//
// The platform relay accepts response bodies up to 1 MiB, so the row table is
// only ever returned a page at a time.

const (
	maxResponse = 1 << 20
	maxTaskBody = 12288
	maxPageSize = 200
)

type server struct {
	store  *Store
	runner *Runner
	auth   *authority
	slots  []Slot
	loc    *time.Location
	now    func() time.Time
}

func newServer(store *Store, runner *Runner, auth *authority) *server {
	loc, err := time.LoadLocation(scheduleZone)
	if err != nil {
		loc = time.UTC
	}
	return &server{store: store, runner: runner, auth: auth, slots: DefaultSlots(), loc: loc, now: time.Now}
}

func (s *server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Header.Get("Cookie") != "" || r.Header.Get("Authorization") != "" {
		writeError(w, http.StatusBadRequest, "refused")
		return
	}
	switch {
	case r.Method == http.MethodGet && r.URL.Path == "/health/ready":
		if r.URL.RawQuery != "" {
			writeError(w, http.StatusBadRequest, "refused")
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"protocol": "portal.backend/1", "ready": true, "data_format": readinessDataFormat})
	case r.Method == http.MethodPost && r.URL.Path == "/v1/handshake":
		s.handshake(w, r)
	case r.Method == http.MethodPost && r.URL.Path == "/v1/tasks/run":
		s.task(w, r)
	case r.Method == http.MethodPost && strings.HasPrefix(r.URL.Path, "/v1/admin/jobs/"):
		s.adminRunNow(w, r)
	case r.Method == http.MethodGet && strings.HasPrefix(r.URL.Path, "/v1/admin/"):
		claims, err := s.auth.verifyViewer(r.Header.Get("X-Portal-Assertion"), r.Method, r.URL.RequestURI(), nil)
		if err != nil || !claims.Admin() {
			writeError(w, http.StatusForbidden, "forbidden")
			return
		}
		s.adminRead(w, r)
	case r.Method == http.MethodGet && strings.HasPrefix(r.URL.Path, "/v1/"):
		// Reader data routes accept admin assertions too: an app admin may
		// read the dashboards inside the admin page, and this app holds no
		// audience-sensitive data beyond those dashboards.
		if _, err := s.auth.verifyViewer(r.Header.Get("X-Portal-Assertion"), r.Method, r.URL.RequestURI(), nil); err != nil {
			writeError(w, http.StatusForbidden, "forbidden")
			return
		}
		s.read(w, r)
	default:
		writeError(w, http.StatusNotFound, "not_found")
	}
}

func (s *server) handshake(w http.ResponseWriter, r *http.Request) {
	if r.URL.RawQuery != "" || r.Header.Get("Content-Type") != "application/json" {
		writeError(w, http.StatusBadRequest, "refused")
		return
	}
	raw, err := io.ReadAll(io.LimitReader(r.Body, 8193))
	var req struct {
		Challenge string `json:"challenge"`
	}
	if err != nil || len(raw) == 0 || len(raw) > 8192 || strictJSON(raw, &req) != nil ||
		req.Challenge == "" || len(req.Challenge) > 4096 {
		writeError(w, http.StatusBadRequest, "refused")
		return
	}
	answer, err := s.auth.answerChallenge(req.Challenge)
	if err != nil {
		writeError(w, http.StatusConflict, "registration_unavailable")
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"answer": answer})
}

func (s *server) task(w http.ResponseWriter, r *http.Request) {
	if r.URL.RawQuery != "" || r.Header.Get("Content-Type") != "application/json" ||
		r.Header.Get("X-Portal-Assertion") != "" {
		taskFailure(w, "run_request_invalid")
		return
	}
	raw, err := io.ReadAll(io.LimitReader(r.Body, maxTaskBody+1))
	var req taskRequest
	if err != nil || len(raw) == 0 || len(raw) > maxTaskBody || strictJSON(raw, &req) != nil ||
		req.Format != taskRequestFormat || req.TaskID == "" || len(req.TaskID) > 128 ||
		!strings.HasPrefix(req.OccurrenceID, "run:") {
		taskFailure(w, "run_request_invalid")
		return
	}
	if s.auth.validateServiceIdentity(r.Header.Get("X-Portal-Service-Identity"), "tasks.schedule") != nil {
		taskFailure(w, "run_authority_invalid")
		return
	}
	var payload struct {
		Job string `json:"job"`
	}
	if strictJSON(req.Payload, &payload) != nil || payload.Job == "" {
		taskFailure(w, "run_payload_invalid")
		return
	}
	run, duplicate, err := s.runner.Submit(payload.Job, req.TaskID, req.OccurrenceID)
	switch {
	case errors.Is(err, errUnknownJob):
		taskFailure(w, "run_payload_invalid")
		return
	case errors.Is(err, errConflict):
		taskFailure(w, "run_identity_conflict")
		return
	case errors.Is(err, errQueueFull):
		taskFailure(w, "run_queue_full")
		return
	case err != nil:
		taskFailure(w, "run_unavailable")
		return
	}
	result, _ := json.Marshal(map[string]any{"run_id": run.ID, "job": run.Job, "status": run.Status, "duplicate": duplicate})
	sum := sha256.Sum256(result)
	writeJSON(w, http.StatusOK, taskResponse{Format: taskResponseFormat, Outcome: "succeeded",
		Result: result, EvidenceSHA256: hex.EncodeToString(sum[:])})
}

func taskFailure(w http.ResponseWriter, code string) {
	writeJSON(w, http.StatusOK, taskResponse{Format: taskResponseFormat, Outcome: "failed", ErrorCode: code})
}

func validField(name string) bool {
	if name == "" || len(name) > 64 {
		return false
	}
	for _, c := range name {
		if !(c == '_' || c >= 'a' && c <= 'z' || c >= '0' && c <= '9') {
			return false
		}
	}
	return true
}

func (s *server) read(w http.ResponseWriter, r *http.Request) {
	parts := strings.Split(strings.TrimPrefix(r.URL.Path, "/v1/"), "/")
	if len(parts) < 2 || !modules[parts[0]] {
		writeError(w, http.StatusNotFound, "not_found")
		return
	}
	module, query := parts[0], r.URL.Query()
	switch parts[1] {
	case "history", "compare", "streak", "counts":
		s.history(w, r, module, parts, query)
		return
	}
	date := query.Get("date")
	if date != "" && !validDate(date) {
		writeError(w, http.StatusBadRequest, "bad_request")
		return
	}
	switch {
	case len(parts) == 2 && parts[1] == "dates" && r.URL.RawQuery == "":
		dates, err := s.store.Dates(module)
		if err != nil {
			writeError(w, http.StatusConflict, "unavailable")
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"module": module, "dates": dates})
	case len(parts) == 2 && parts[1] == "summary" && onlyKeys(query, "date"):
		snap, ok := s.load(w, module, date)
		if ok {
			writeJSON(w, http.StatusOK, map[string]any{"module": module, "as_of": snap.AsOf, "summary": snap.Summary})
		}
	case len(parts) == 2 && parts[1] == "rows":
		q, ok := parseRowQuery(query)
		if !ok {
			writeError(w, http.StatusBadRequest, "bad_request")
			return
		}
		snap, ok := s.load(w, module, date)
		if ok {
			items, total := queryRows(snap.Rows, q)
			writeJSON(w, http.StatusOK, map[string]any{"module": module, "as_of": snap.AsOf,
				"page": q.Page, "size": q.Size, "total": total, "items": items})
		}
	case len(parts) == 3 && parts[1] == "rows" && parts[2] != "" && onlyKeys(query, "date"):
		snap, ok := s.load(w, module, date)
		if !ok {
			return
		}
		i, found := snap.index[parts[2]]
		if !found {
			writeError(w, http.StatusNotFound, "not_found")
			return
		}
		var detail json.RawMessage = []byte("null")
		if d, ok := snap.Details[parts[2]]; ok {
			detail = d
		}
		writeJSON(w, http.StatusOK, map[string]any{"module": module, "as_of": snap.AsOf, "row": snap.Rows[i], "detail": detail})
	default:
		writeError(w, http.StatusBadRequest, "bad_request")
	}
}

func (s *server) load(w http.ResponseWriter, module, date string) (*snapshot, bool) {
	snap, err := s.store.Load(module, date)
	switch {
	case errors.Is(err, errNotFound):
		writeError(w, http.StatusNotFound, "no_data")
		return nil, false
	case err != nil:
		writeError(w, http.StatusConflict, "unavailable")
		return nil, false
	}
	return snap, true
}

func onlyKeys(q url.Values, allowed ...string) bool {
	for key := range q {
		ok := false
		for _, a := range allowed {
			ok = ok || key == a
		}
		if !ok {
			return false
		}
	}
	return true
}

func parseRowQuery(q url.Values) (rowQuery, bool) {
	out := rowQuery{Page: 1, Size: 50, Filters: map[string]string{}}
	for key, values := range q {
		if len(values) != 1 {
			return out, false
		}
		v := values[0]
		switch {
		case key == "date":
		case key == "page" || key == "size":
			n, err := strconv.Atoi(v)
			if err != nil || n < 1 || (key == "size" && n > maxPageSize) || n > 1_000_000 {
				return out, false
			}
			if key == "page" {
				out.Page = n
			} else {
				out.Size = n
			}
		case key == "sort":
			if !validField(v) {
				return out, false
			}
			out.Sort = v
		case key == "order":
			if v != "asc" && v != "desc" {
				return out, false
			}
			out.Desc = v == "desc"
		case key == "q":
			if len(v) > 64 {
				return out, false
			}
			out.Search = v
		case strings.HasPrefix(key, "f."):
			field := strings.TrimPrefix(key, "f.")
			if !validField(field) || v == "" || len(v) > 64 || len(out.Filters) >= 8 {
				return out, false
			}
			out.Filters[field] = v
		default:
			return out, false
		}
	}
	return out, true
}

// writeError answers with a JSON body and one of the statuses the platform
// relay passes through (400, 403, 404, 409, 422, 429).
func writeError(w http.ResponseWriter, status int, code string) {
	raw, _ := json.Marshal(map[string]string{"error": code})
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write(raw)
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	raw, err := json.Marshal(value)
	if err != nil {
		writeError(w, http.StatusUnprocessableEntity, "unencodable")
		return
	}
	if len(raw) > maxResponse {
		writeError(w, http.StatusUnprocessableEntity, "response_too_large")
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write(raw)
}
