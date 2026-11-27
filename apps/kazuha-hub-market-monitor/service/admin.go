package main

import (
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"
)

// Admin surface: job schedule, run history, run logs and "Run now". Every
// route here needs an assertion the platform signed for the app's admin view.

const (
	maxAdminLogBytes  = 64 << 10
	maxRunNowBody     = 512
	manualTaskPrefix  = "manual/"
	manualOccurrence  = "manual:"
	scheduleTaskStart = "schedule/"
)

var requestIDPattern = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)

// AdminRun is a run as an app admin sees it: the source of the run and its
// outputs, but not the platform task identity.
type AdminRun struct {
	ID         string   `json:"id"`
	Job        string   `json:"job"`
	Source     string   `json:"source"`
	Status     string   `json:"status"`
	Attempt    int      `json:"attempt"`
	QueuedAt   string   `json:"queued_at"`
	StartedAt  string   `json:"started_at,omitempty"`
	FinishedAt string   `json:"finished_at,omitempty"`
	ExitCode   int      `json:"exit_code"`
	Error      string   `json:"error,omitempty"`
	Installed  []string `json:"installed,omitempty"`
	// Progress is set while the run is running, Reason once it failed.
	Progress     *AdminProgress `json:"progress,omitempty"`
	Reason       string         `json:"reason,omitempty"`
	ReasonDetail string         `json:"reason_detail,omitempty"`
}

// runSource derives who started a run from its task ID: the scheduler uses
// "schedule/<job>/...", the empty-store bootstrap "bootstrap/<job>/<day>", Run
// now "manual/<request id>", and anything else came from a platform task.
func runSource(run Run) string {
	switch {
	case strings.HasPrefix(run.TaskID, scheduleTaskStart):
		return "schedule"
	case strings.HasPrefix(run.TaskID, manualTaskPrefix):
		return "manual"
	case strings.HasPrefix(run.TaskID, "bootstrap/"):
		return "bootstrap"
	}
	return "platform"
}

func adminRunOf(run Run) AdminRun {
	return AdminRun{ID: run.ID, Job: run.Job, Source: runSource(run), Status: run.Status, Attempt: run.Attempt,
		QueuedAt: run.QueuedAt, StartedAt: run.StartedAt, FinishedAt: run.FinishedAt, ExitCode: run.ExitCode,
		Error: run.Error, Installed: run.Installed}
}

// allRuns returns a copy of the indexed runs, newest first.
func (r *Runner) allRuns() []Run {
	r.mu.Lock()
	defer r.mu.Unlock()
	return append([]Run(nil), r.runs...)
}

type slotView struct {
	Days     []string `json:"days"`
	Hour     int      `json:"hour"`
	Minute   int      `json:"minute"`
	Fallback bool     `json:"fallback"`
}

type jobView struct {
	Name     string     `json:"name"`
	Schedule []slotView `json:"schedule"`
	NextRun  string     `json:"next_run,omitempty"`
	LastRun  *AdminRun  `json:"last_run"`
	// TypicalSeconds is how long recent successful runs took, 0 if unknown.
	TypicalSeconds int `json:"typical_seconds,omitempty"`
}

func (s *server) adminRead(w http.ResponseWriter, r *http.Request) {
	if r.URL.RawQuery != "" {
		writeError(w, http.StatusBadRequest, "bad_request")
		return
	}
	parts := strings.Split(strings.TrimPrefix(r.URL.Path, "/v1/admin/"), "/")
	switch {
	case len(parts) == 1 && parts[0] == "jobs":
		s.adminJobs(w)
	case len(parts) == 1 && parts[0] == "runs":
		runs := s.runner.allRuns()
		out := make([]AdminRun, len(runs))
		for i, run := range runs {
			if i < reasonedRuns || run.Status == "running" {
				out[i] = s.adminRunView(run)
			} else {
				out[i] = adminRunOf(run)
			}
		}
		writeJSON(w, http.StatusOK, map[string]any{"runs": out})
	case len(parts) == 3 && parts[0] == "runs" && parts[2] == "log":
		s.adminLog(w, parts[1])
	default:
		writeError(w, http.StatusNotFound, "not_found")
	}
}

func (s *server) adminJobs(w http.ResponseWriter) {
	now := s.now()
	names := make([]string, 0, len(s.runner.specs))
	for name := range s.runner.specs {
		names = append(names, name)
	}
	sort.Strings(names)
	jobs := make([]jobView, 0, len(names))
	for _, name := range names {
		view := jobView{Name: name, Schedule: []slotView{}}
		var next time.Time
		for _, sl := range s.slots {
			if sl.Job != name {
				continue
			}
			days := make([]string, len(sl.Days))
			for i, d := range sl.Days {
				days[i] = d.String()
			}
			view.Schedule = append(view.Schedule, slotView{Days: days, Hour: sl.Hour, Minute: sl.Minute, Fallback: sl.Fallback})
			// A fallback slot runs only if the main slot failed, so it is
			// not when the job is next due.
			if sl.Fallback {
				continue
			}
			if t, ok := sl.next(now, s.loc); ok && (next.IsZero() || t.Before(next)) {
				next = t
			}
		}
		if !next.IsZero() {
			view.NextRun = next.Format(time.RFC3339)
		}
		if runs := s.runner.runsOf(name); len(runs) > 0 {
			last := s.adminRunView(runs[0])
			view.LastRun = &last
			view.TypicalSeconds = typicalSeconds(runs)
		}
		jobs = append(jobs, view)
	}
	writeJSON(w, http.StatusOK, map[string]any{"time_zone": s.loc.String(), "jobs": jobs})
}

func (s *server) adminLog(w http.ResponseWriter, id string) {
	run, ok := s.runner.get(id)
	if !ok {
		writeError(w, http.StatusNotFound, "not_found")
		return
	}
	text, truncated, err := readLogTail(filepath.Join(s.runner.dataDir, "runs", run.ID+".log"), maxAdminLogBytes)
	if err != nil {
		writeError(w, http.StatusConflict, "unavailable")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"run_id": run.ID, "log": text, "truncated": truncated})
}

// readLogTail returns at most limit bytes from the end of a file. A run that
// has not written a log yet has an empty one.
func readLogTail(path string, limit int64) (string, bool, error) {
	f, err := os.Open(path)
	if errors.Is(err, os.ErrNotExist) {
		return "", false, nil
	}
	if err != nil {
		return "", false, err
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return "", false, err
	}
	truncated := info.Size() > limit
	if truncated {
		if _, err := f.Seek(info.Size()-limit, io.SeekStart); err != nil {
			return "", false, err
		}
	}
	raw, err := io.ReadAll(io.LimitReader(f, limit))
	if err != nil {
		return "", false, err
	}
	return strings.ToValidUTF8(string(raw), "�"), truncated, nil
}

// adminRunNow starts a job by hand. The request ID names the click: sending
// it again returns the same run instead of queueing a second one.
func (s *server) adminRunNow(w http.ResponseWriter, r *http.Request) {
	raw, err := io.ReadAll(io.LimitReader(r.Body, maxRunNowBody+1))
	if err != nil || len(raw) > maxRunNowBody {
		writeError(w, http.StatusBadRequest, "bad_request")
		return
	}
	claims, err := s.auth.verifyViewer(r.Header.Get("X-Portal-Assertion"), r.Method, r.URL.RequestURI(), raw)
	if err != nil || !claims.Admin() {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}
	parts := strings.Split(strings.TrimPrefix(r.URL.Path, "/v1/admin/jobs/"), "/")
	var req struct {
		RequestID string `json:"request_id"`
	}
	if r.URL.RawQuery != "" || len(parts) != 2 || parts[1] != "run" || parts[0] == "" ||
		r.Header.Get("Content-Type") != "application/json" ||
		strictJSON(raw, &req) != nil || !requestIDPattern.MatchString(req.RequestID) {
		writeError(w, http.StatusBadRequest, "bad_request")
		return
	}
	id := strings.ToLower(req.RequestID)
	run, duplicate, err := s.runner.SubmitIfIdle(parts[0], manualTaskPrefix+id, manualOccurrence+id)
	switch {
	case errors.Is(err, errUnknownJob):
		writeError(w, http.StatusNotFound, "not_found")
		return
	case errors.Is(err, errQueueFull):
		writeError(w, http.StatusConflict, "queue_full")
		return
	case errors.Is(err, errAlreadyActive):
		writeError(w, http.StatusConflict, "already_active")
		return
	case errors.Is(err, errConflict):
		// The same request ID was used for another job.
		writeError(w, http.StatusConflict, "conflict")
		return
	case err != nil:
		writeError(w, http.StatusConflict, "unavailable")
		return
	}
	writeJSON(w, http.StatusAccepted, map[string]any{"run": adminRunOf(run), "duplicate": duplicate})
}
