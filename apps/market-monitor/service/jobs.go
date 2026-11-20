package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"syscall"
	"time"
)

// A platform background task only triggers a job; the job itself can run for
// far longer than the task request may, so the runner executes it inside the
// container, one at a time in submission order, and records its progress.
// Jobs write snapshot JSON into MM_OUTPUT_DIR; the runner validates and
// installs them, so the Go service stays the only writer of snapshots.
//
// Jobs are idempotent per as-of date (a re-run replaces that date's
// snapshot), so a run cut short by a restart is queued again. Only runs that
// were running count against maxAttempts.

const (
	runsFormat  = "market-monitor.runs/1"
	maxRuns     = 200
	maxQueue    = 16
	maxAttempts = 3
	maxLogBytes = 256 << 10
)

type JobSpec struct {
	Name    string
	Command []string
	Timeout time.Duration
}

// Run is the stored record. Error is a short code; the full reason goes to
// the run's log, which only operators read.
type Run struct {
	ID           string   `json:"id"`
	Job          string   `json:"job"`
	TaskID       string   `json:"task_id"`
	OccurrenceID string   `json:"occurrence_id"`
	Status       string   `json:"status"`
	Attempt      int      `json:"attempt"`
	QueuedAt     string   `json:"queued_at"`
	StartedAt    string   `json:"started_at,omitempty"`
	FinishedAt   string   `json:"finished_at,omitempty"`
	ExitCode     int      `json:"exit_code"`
	Error        string   `json:"error,omitempty"`
	Installed    []string `json:"installed,omitempty"`
}

// RunView is what viewers see: no platform task identity, no raw errors.
type RunView struct {
	ID         string   `json:"id"`
	Job        string   `json:"job"`
	Status     string   `json:"status"`
	Attempt    int      `json:"attempt"`
	QueuedAt   string   `json:"queued_at"`
	StartedAt  string   `json:"started_at,omitempty"`
	FinishedAt string   `json:"finished_at,omitempty"`
	Error      string   `json:"error,omitempty"`
	Installed  []string `json:"installed,omitempty"`
}

type runsFile struct {
	Format string `json:"format"`
	Runs   []Run  `json:"runs"`
}

var (
	errUnknownJob = errors.New("unknown job")
	errQueueFull  = errors.New("job queue full")
	errConflict   = errors.New("task identity changed")
)

type Runner struct {
	dataDir string
	specs   map[string]JobSpec
	store   *Store
	now     func() time.Time

	mu    sync.Mutex
	runs  []Run // newest first
	queue chan string
}

func NewRunner(dataDir string, specs []JobSpec, store *Store) (*Runner, error) {
	r := &Runner{
		dataDir: dataDir, specs: map[string]JobSpec{}, store: store,
		now: func() time.Time { return time.Now().UTC() }, queue: make(chan string, maxQueue),
	}
	for _, spec := range specs {
		if spec.Name == "" || len(spec.Command) == 0 || spec.Timeout <= 0 {
			return nil, fmt.Errorf("invalid job spec %q", spec.Name)
		}
		r.specs[spec.Name] = spec
	}
	if err := os.MkdirAll(filepath.Join(dataDir, "runs"), 0700); err != nil {
		return nil, err
	}
	raw, err := os.ReadFile(r.indexPath())
	switch {
	case errors.Is(err, os.ErrNotExist):
	case err != nil:
		return nil, err
	default:
		var f runsFile
		if json.Unmarshal(raw, &f) != nil || f.Format != runsFormat {
			return nil, errors.New("run index unreadable")
		}
		r.runs = f.Runs
	}
	// Settle runs that were cut short: queue them again, oldest first, or
	// give up after maxAttempts.
	changed := false
	for i := len(r.runs) - 1; i >= 0; i-- {
		run := &r.runs[i]
		if run.Status != "queued" && run.Status != "running" {
			continue
		}
		changed = true
		// Only a run that was actually running used up an attempt; one that
		// was still waiting keeps its attempt number.
		wasRunning := run.Status == "running"
		if _, known := r.specs[run.Job]; !known || (wasRunning && run.Attempt >= maxAttempts) || len(r.queue) == cap(r.queue) {
			run.Status, run.Error, run.FinishedAt = "interrupted", "interrupted", r.stamp()
			continue
		}
		if wasRunning {
			run.Attempt++
		}
		run.Status, run.StartedAt = "queued", ""
		r.queue <- run.ID
	}
	if changed {
		if err := r.persistLocked(); err != nil {
			return nil, err
		}
	}
	_ = os.RemoveAll(filepath.Join(dataDir, "staging"))
	return r, nil
}

func (r *Runner) indexPath() string { return filepath.Join(r.dataDir, "runs", "index.json") }
func (r *Runner) stamp() string     { return r.now().Format(time.RFC3339) }

func (r *Runner) persistLocked() error {
	raw, err := json.Marshal(runsFile{Format: runsFormat, Runs: r.runs})
	if err != nil {
		return err
	}
	return writeAtomic(r.indexPath(), raw)
}

// Submit queues a job for a platform task. A task ID always maps to one run:
// a redelivery with the same job and occurrence returns that run, while a
// different job or occurrence under the same task ID is refused.
func (r *Runner) Submit(job, taskID, occurrenceID string) (Run, bool, error) {
	if _, ok := r.specs[job]; !ok {
		return Run{}, false, errUnknownJob
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	for _, run := range r.runs {
		if run.TaskID == taskID {
			if run.Job != job || run.OccurrenceID != occurrenceID {
				return Run{}, false, errConflict
			}
			return run, true, nil
		}
	}
	if len(r.queue) == cap(r.queue) {
		return Run{}, false, errQueueFull
	}
	var id [8]byte
	if _, err := rand.Read(id[:]); err != nil {
		return Run{}, false, err
	}
	run := Run{
		ID:  r.now().Format("20060102T150405Z") + "-" + hex.EncodeToString(id[:]),
		Job: job, TaskID: taskID, OccurrenceID: occurrenceID,
		Status: "queued", Attempt: 1, QueuedAt: r.stamp(),
	}
	previous := r.runs
	r.runs = append([]Run{run}, r.runs...)
	var trimmed []Run
	if len(r.runs) > maxRuns {
		trimmed = r.runs[maxRuns:]
		r.runs = r.runs[:maxRuns]
	}
	// Record the run before it can start, so an executing run is always on disk.
	if err := r.persistLocked(); err != nil {
		r.runs = previous
		return Run{}, false, err
	}
	for _, old := range trimmed {
		os.Remove(filepath.Join(r.dataDir, "runs", old.ID+".log"))
	}
	r.queue <- run.ID // cannot block: capacity was checked under the same lock
	return run, false, nil
}

func (r *Runner) Runs() []RunView {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := make([]RunView, len(r.runs))
	for i, run := range r.runs {
		out[i] = RunView{ID: run.ID, Job: run.Job, Status: run.Status, Attempt: run.Attempt,
			QueuedAt: run.QueuedAt, StartedAt: run.StartedAt, FinishedAt: run.FinishedAt,
			Error: run.Error, Installed: run.Installed}
	}
	return out
}

func (r *Runner) get(id string) (Run, bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	for _, run := range r.runs {
		if run.ID == id {
			return run, true
		}
	}
	return Run{}, false
}

// update changes a run and persists it. A failed persist is retried by the
// next update; the in-memory state stays authoritative meanwhile.
func (r *Runner) update(id string, change func(*Run)) {
	r.mu.Lock()
	defer r.mu.Unlock()
	for i := range r.runs {
		if r.runs[i].ID == id {
			change(&r.runs[i])
			_ = r.persistLocked()
			return
		}
	}
}

// Start launches the single worker and returns a function that stops it,
// killing a running job's process group.
func (r *Runner) Start() func() {
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		defer close(done)
		for {
			select {
			case <-ctx.Done():
				return
			case id := <-r.queue:
				// Both cases can be ready at once and select picks at random;
				// on shutdown leave the run queued for the next start.
				if ctx.Err() != nil {
					return
				}
				r.execute(ctx, id)
			}
		}
	}()
	return func() { cancel(); <-done }
}

type cappedWriter struct {
	f       *os.File
	written int
}

func (w *cappedWriter) Write(p []byte) (int, error) {
	if room := maxLogBytes - w.written; room > 0 {
		n := min(len(p), room)
		m, err := w.f.Write(p[:n])
		w.written += m
		if err != nil {
			return m, err
		}
	}
	return len(p), nil
}

func (r *Runner) execute(ctx context.Context, id string) {
	run, ok := r.get(id)
	if !ok || run.Status != "queued" || ctx.Err() != nil {
		return
	}
	spec := r.specs[run.Job]
	r.update(id, func(run *Run) { run.Status, run.StartedAt = "running", r.stamp() })
	staging := filepath.Join(r.dataDir, "staging", id)
	// Append, so a requeued attempt keeps the earlier attempts' output.
	logFile, logErr := os.OpenFile(filepath.Join(r.dataDir, "runs", id+".log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	note := func(format string, args ...any) {
		if logErr == nil {
			fmt.Fprintf(logFile, "\n[market-monitor] "+format+"\n", args...)
		}
	}
	note("attempt %d of %s started", run.Attempt, run.Job)
	// Clean staging before publishing a final status, so a finished run never
	// leaves files behind for an observer to see.
	finish := func(status string, code int, errCode string, installed []string) {
		os.RemoveAll(staging)
		if logErr == nil {
			logFile.Close()
		}
		r.update(id, func(run *Run) {
			run.Status, run.ExitCode, run.Error, run.Installed, run.FinishedAt = status, code, errCode, installed, r.stamp()
		})
	}
	if logErr != nil {
		finish("failed", -1, "log_unavailable", nil)
		return
	}
	if err := os.MkdirAll(staging, 0700); err != nil {
		note("staging: %v", err)
		finish("failed", -1, "staging_unavailable", nil)
		return
	}
	runCtx, cancel := context.WithTimeout(ctx, spec.Timeout)
	defer cancel()
	cmd := exec.CommandContext(runCtx, spec.Command[0], spec.Command[1:]...)
	cmd.Env = append(os.Environ(), "MM_DATA_DIR="+r.dataDir, "MM_OUTPUT_DIR="+staging, "MM_RUN_ID="+id)
	cmd.Stdout = &cappedWriter{f: logFile}
	cmd.Stderr = cmd.Stdout
	// The job gets its own process group; the whole group is killed on
	// timeout or shutdown and again after the job exits, so nothing it
	// started outlives it.
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error { return syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL) }
	cmd.WaitDelay = 2 * time.Second
	if err := cmd.Start(); err != nil {
		if ctx.Err() != nil {
			// Shutdown landed between the check above and Start: leave the
			// run "running" so the next start queues it again.
			note("stopped by service shutdown before start")
			os.RemoveAll(staging)
			logFile.Close()
			return
		}
		note("start: %v", err)
		finish("failed", -1, "start_failed", nil)
		return
	}
	waitErr := make(chan error, 1)
	go func() { waitErr <- cmd.Wait() }()
	var err error
	select {
	case err = <-waitErr:
	case <-runCtx.Done():
		err = <-waitErr
	}
	_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	switch {
	case ctx.Err() != nil:
		// Shutting down: leave the run "running" so the next start queues it
		// again.
		note("stopped by service shutdown")
		os.RemoveAll(staging)
		logFile.Close()
		return
	case runCtx.Err() == context.DeadlineExceeded:
		note("timeout after %s", spec.Timeout)
		finish("failed", -1, "timeout", nil)
		return
	case err != nil && !(errors.Is(err, exec.ErrWaitDelay) && cmd.ProcessState.Success()):
		note("job exited: %v", err)
		finish("failed", cmd.ProcessState.ExitCode(), "exit_status", nil)
		return
	}
	installed, err := r.installOutputs(staging)
	if err != nil {
		note("outputs: %v", err)
		finish("failed", 0, "output_invalid", installed)
		return
	}
	finish("succeeded", 0, "", installed)
}

// installOutputs validates every <module>.json in the staging directory
// before installing any. Installation itself is one module at a time; if a
// later install fails, the modules already installed are reported.
func (r *Runner) installOutputs(staging string) ([]string, error) {
	entries, err := os.ReadDir(staging)
	if err != nil {
		return nil, err
	}
	type output struct {
		module string
		raw    []byte
	}
	var outputs []output
	for _, e := range entries {
		name := e.Name()
		if !e.Type().IsRegular() || !strings.HasSuffix(name, ".json") {
			return nil, fmt.Errorf("unexpected output %q", name)
		}
		module := strings.TrimSuffix(name, ".json")
		raw, err := os.ReadFile(filepath.Join(staging, name))
		if err != nil {
			return nil, err
		}
		snap, err := parseSnapshot(raw)
		if err != nil {
			return nil, fmt.Errorf("output %s: %v", name, err)
		}
		if snap.Module != module {
			return nil, fmt.Errorf("output %s declares module %q", name, snap.Module)
		}
		outputs = append(outputs, output{module, raw})
	}
	installed := []string{}
	for _, o := range outputs {
		asOf, err := r.store.Install(o.module, o.raw)
		if err != nil {
			sort.Strings(installed)
			return installed, fmt.Errorf("install %s: %v", o.module, err)
		}
		installed = append(installed, o.module+"/"+asOf)
	}
	sort.Strings(installed)
	return installed, nil
}
