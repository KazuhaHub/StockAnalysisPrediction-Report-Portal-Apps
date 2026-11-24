package main

import (
	"errors"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"
)

// fakeJob writes a shell script that copies a snapshot into MM_OUTPUT_DIR and
// then exits with the given code.
func fakeJob(t *testing.T, dir, name, snapshot string, exit int) JobSpec {
	t.Helper()
	src := filepath.Join(dir, name+".snapshot.json")
	if err := os.WriteFile(src, []byte(snapshot), 0600); err != nil {
		t.Fatal(err)
	}
	body := "#!/bin/sh\necho running " + name + "\n"
	if snapshot != "" {
		body += "cp '" + src + "' \"$MM_OUTPUT_DIR/" + name + ".json\"\n"
		// Margin, panorama and etf jobs also write their history file.
		if parsed, err := parseSnapshot([]byte(snapshot)); err == nil && historyModules[name] {
			hist := filepath.Join(dir, name+".history.parquet")
			if err := os.WriteFile(hist, historyFile(t, histSpec{module: name, asOf: parsed.AsOf, rows: parsed.Rows}), 0600); err != nil {
				t.Fatal(err)
			}
			body += "cp '" + hist + "' \"$MM_OUTPUT_DIR/" + name + ".history.parquet\"\n"
		}
	}
	body += "exit " + strconv.Itoa(exit) + "\n"
	return scriptJob(t, dir, name, body, 10*time.Second)
}

func scriptJob(t *testing.T, dir, name, body string, timeout time.Duration) JobSpec {
	t.Helper()
	script := filepath.Join(dir, name+".sh")
	if err := os.WriteFile(script, []byte(body), 0700); err != nil {
		t.Fatal(err)
	}
	return JobSpec{Name: name, Command: []string{script}, Timeout: timeout}
}

func waitRun(t *testing.T, r *Runner, id string) Run {
	t.Helper()
	deadline := time.Now().Add(15 * time.Second)
	for time.Now().Before(deadline) {
		if run, ok := r.get(id); ok && (run.Status == "succeeded" || run.Status == "failed") {
			return run
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("run %s did not finish: %+v", id, r.Runs())
	return Run{}
}

// processGone waits for the pid written to file to stop existing.
func processGone(t *testing.T, pidFile string) bool {
	t.Helper()
	var pid int
	for i := 0; i < 100 && pid == 0; i++ {
		raw, _ := os.ReadFile(pidFile)
		pid, _ = strconv.Atoi(strings.TrimSpace(string(raw)))
		time.Sleep(10 * time.Millisecond)
	}
	if pid == 0 {
		t.Fatal("child pid never written")
	}
	for i := 0; i < 100; i++ {
		if syscall.Kill(pid, 0) != nil {
			return true
		}
		time.Sleep(20 * time.Millisecond)
	}
	return false
}

func TestRunnerInstallsSnapshotsOnSuccess(t *testing.T) {
	data, scripts := t.TempDir(), t.TempDir()
	store := NewStore(data)
	r, err := NewRunner(data, []JobSpec{fakeJob(t, scripts, "margin", string(testSnapshot("margin", "2026-11-18")), 0)}, store)
	if err != nil {
		t.Fatal(err)
	}
	stop := r.Start()
	defer stop()
	run, dup, err := r.Submit("margin", "task-1", "run:1")
	if err != nil || dup {
		t.Fatal(err, dup)
	}
	done := waitRun(t, r, run.ID)
	if done.Status != "succeeded" || strings.Join(done.Installed, ",") != "margin/2026-11-18" {
		t.Fatalf("run %+v", done)
	}
	if _, err := store.Load("margin", "2026-11-18"); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(data, "staging", run.ID)); !os.IsNotExist(err) {
		t.Fatalf("staging not removed: %v", err)
	}
	log, err := os.ReadFile(filepath.Join(data, "runs", run.ID+".log"))
	if err != nil || !strings.Contains(string(log), "running margin") {
		t.Fatalf("log %q %v", log, err)
	}
}

func TestRunnerFailsOnExitCodeAndInstallsNothing(t *testing.T) {
	data, scripts := t.TempDir(), t.TempDir()
	store := NewStore(data)
	r, _ := NewRunner(data, []JobSpec{fakeJob(t, scripts, "margin", string(testSnapshot("margin", "2026-11-18")), 3)}, store)
	stop := r.Start()
	defer stop()
	run, _, _ := r.Submit("margin", "task-1", "run:1")
	done := waitRun(t, r, run.ID)
	if done.Status != "failed" || done.ExitCode != 3 || done.Error != "exit_status" {
		t.Fatalf("run %+v", done)
	}
	if dates, _ := store.Dates("margin"); len(dates) != 0 {
		t.Fatalf("failed run installed %v", dates)
	}
}

func TestRunnerFailsOnInvalidOutputAndLogsTheReason(t *testing.T) {
	data, scripts := t.TempDir(), t.TempDir()
	r, _ := NewRunner(data, []JobSpec{fakeJob(t, scripts, "margin", `{"format":"nope"}`, 0)}, NewStore(data))
	stop := r.Start()
	defer stop()
	run, _, _ := r.Submit("margin", "task-1", "run:1")
	if done := waitRun(t, r, run.ID); done.Status != "failed" || done.Error != "output_invalid" {
		t.Fatalf("run %+v", done)
	}
	log, _ := os.ReadFile(filepath.Join(data, "runs", run.ID+".log"))
	if !strings.Contains(string(log), "invalid snapshot") {
		t.Fatalf("reason not logged: %q", log)
	}
}

func TestRunnerRefusesOutputForAnotherModuleName(t *testing.T) {
	data, scripts := t.TempDir(), t.TempDir()
	spec := fakeJob(t, scripts, "margin", string(testSnapshot("etf", "2026-11-18")), 0)
	r, _ := NewRunner(data, []JobSpec{spec}, NewStore(data))
	stop := r.Start()
	defer stop()
	run, _, _ := r.Submit("margin", "task-1", "run:1")
	if done := waitRun(t, r, run.ID); done.Status != "failed" {
		t.Fatalf("run %+v", done)
	}
}

func TestRunnerTaskIdentity(t *testing.T) {
	data, scripts := t.TempDir(), t.TempDir()
	r, _ := NewRunner(data, []JobSpec{fakeJob(t, scripts, "margin", "", 0), fakeJob(t, scripts, "etf", "", 0)}, NewStore(data))
	first, dup, err := r.Submit("margin", "task-1", "run:1")
	if err != nil || dup {
		t.Fatal(err)
	}
	again, dup, err := r.Submit("margin", "task-1", "run:1")
	if err != nil || !dup || again.ID != first.ID {
		t.Fatalf("redelivery %+v %v %v", again, dup, err)
	}
	if _, _, err := r.Submit("etf", "task-1", "run:1"); !errors.Is(err, errConflict) {
		t.Fatalf("same task, other job: %v", err)
	}
	if _, _, err := r.Submit("margin", "task-1", "run:2"); !errors.Is(err, errConflict) {
		t.Fatalf("same task, other occurrence: %v", err)
	}
	if _, _, err := r.Submit("panorama", "task-2", "run:1"); !errors.Is(err, errUnknownJob) {
		t.Fatalf("unknown job: %v", err)
	}
	if _, dup, err := r.Submit("margin", "task-2", "run:1"); err != nil || dup {
		t.Fatalf("new task: %v %v", dup, err)
	}
}

func TestRunnerQueueFullLeavesNoRecord(t *testing.T) {
	data, scripts := t.TempDir(), t.TempDir()
	r, _ := NewRunner(data, []JobSpec{fakeJob(t, scripts, "margin", "", 0)}, NewStore(data))
	for i := 0; i < maxQueue; i++ {
		if _, _, err := r.Submit("margin", "task-"+strconv.Itoa(i), "run:1"); err != nil {
			t.Fatal(i, err)
		}
	}
	if _, _, err := r.Submit("margin", "task-x", "run:1"); !errors.Is(err, errQueueFull) {
		t.Fatalf("over capacity: %v", err)
	}
	if n := len(r.Runs()); n != maxQueue {
		t.Fatalf("refused run recorded: %d", n)
	}
}

func TestRunnerRunsJobsOneAtATimeInOrder(t *testing.T) {
	data, scripts := t.TempDir(), t.TempDir()
	marker := filepath.Join(scripts, "order.txt")
	mk := func(name string) JobSpec {
		return scriptJob(t, scripts, name, "#!/bin/sh\nif [ -e '"+marker+".lock' ]; then echo overlap >> '"+marker+"'; fi\n"+
			"touch '"+marker+".lock'\nsleep 0.2\necho "+name+" >> '"+marker+"'\nrm '"+marker+".lock'\n", 10*time.Second)
	}
	r, _ := NewRunner(data, []JobSpec{mk("marketdata"), mk("sentiment")}, NewStore(data))
	a, _, _ := r.Submit("marketdata", "t1", "run:1")
	b, _, _ := r.Submit("sentiment", "t2", "run:1")
	stop := r.Start()
	defer stop()
	waitRun(t, r, a.ID)
	waitRun(t, r, b.ID)
	got, _ := os.ReadFile(marker)
	if string(got) != "marketdata\nsentiment\n" {
		t.Fatalf("jobs overlapped or reordered: %q", got)
	}
}

func TestRunnerTimeoutKillsTheWholeJob(t *testing.T) {
	data, scripts := t.TempDir(), t.TempDir()
	pidFile := filepath.Join(scripts, "child.pid")
	spec := scriptJob(t, scripts, "margin", "#!/bin/sh\nsleep 30 &\necho $! > '"+pidFile+"'\nwait\n", 500*time.Millisecond)
	r, _ := NewRunner(data, []JobSpec{spec}, NewStore(data))
	stop := r.Start()
	defer stop()
	run, _, _ := r.Submit("margin", "t1", "run:1")
	if done := waitRun(t, r, run.ID); done.Status != "failed" || done.Error != "timeout" {
		t.Fatalf("run %+v", done)
	}
	if !processGone(t, pidFile) {
		t.Fatal("child of a timed-out job survived")
	}
}

func TestRunnerSucceedsAndKillsALeftoverChild(t *testing.T) {
	data, scripts := t.TempDir(), t.TempDir()
	pidFile := filepath.Join(scripts, "child.pid")
	src := filepath.Join(scripts, "snap.json")
	if err := os.WriteFile(src, testSnapshot("margin", "2026-11-18"), 0600); err != nil {
		t.Fatal(err)
	}
	// The child keeps the inherited stdout open, which used to make Wait
	// report an I/O error and fail a job that had exited 0.
	hist := filepath.Join(scripts, "snap.history.parquet")
	if err := os.WriteFile(hist, testHistory(t, "margin", "2026-11-18"), 0600); err != nil {
		t.Fatal(err)
	}
	spec := scriptJob(t, scripts, "margin", "#!/bin/sh\ncp '"+src+"' \"$MM_OUTPUT_DIR/margin.json\"\n"+
		"cp '"+hist+"' \"$MM_OUTPUT_DIR/margin.history.parquet\"\n"+
		"sleep 30 &\necho $! > '"+pidFile+"'\nexit 0\n", 20*time.Second)
	r, _ := NewRunner(data, []JobSpec{spec}, NewStore(data))
	stop := r.Start()
	defer stop()
	run, _, _ := r.Submit("margin", "t1", "run:1")
	if done := waitRun(t, r, run.ID); done.Status != "succeeded" {
		t.Fatalf("run %+v", done)
	}
	if !processGone(t, pidFile) {
		t.Fatal("leftover child survived its job")
	}
}

func TestRunnerRequeuesUnfinishedRunsAfterRestart(t *testing.T) {
	data, scripts := t.TempDir(), t.TempDir()
	spec := fakeJob(t, scripts, "margin", string(testSnapshot("margin", "2026-11-18")), 0)
	r, _ := NewRunner(data, []JobSpec{spec}, NewStore(data))
	queued, _, _ := r.Submit("margin", "t1", "run:1")
	// No worker ran: the process "restarts" with the run still queued.
	r2, err := NewRunner(data, []JobSpec{spec}, NewStore(data))
	if err != nil {
		t.Fatal(err)
	}
	run, _ := r2.get(queued.ID)
	if run.Status != "queued" || run.Attempt != 1 {
		t.Fatalf("not requeued: %+v", run)
	}
	stop := r2.Start()
	defer stop()
	if done := waitRun(t, r2, queued.ID); done.Status != "succeeded" {
		t.Fatalf("requeued run %+v", done)
	}
	if again, dup, err := r2.Submit("margin", "t1", "run:1"); err != nil || !dup || again.ID != queued.ID {
		t.Fatalf("redelivery after restart: %+v %v %v", again, dup, err)
	}
}

// newestOf returns the newest indexed run of a task ID.
func newestOf(t *testing.T, r *Runner, taskID string) Run {
	t.Helper()
	run, ok := r.byTaskID(taskID)
	if !ok {
		t.Fatalf("no run of %s", taskID)
	}
	return run
}

// A run cut short while running (a stop, a quiesce, a generation switch)
// is recorded as interrupted, and its retry is a new run under the same
// task, so the jobs list never shows a stale "running".
func TestARunCutShortIsInterruptedAndRetriedAsANewRun(t *testing.T) {
	data, scripts := t.TempDir(), t.TempDir()
	spec := fakeJob(t, scripts, "margin", string(testSnapshot("margin", "2026-11-18")), 0)
	r, _ := NewRunner(data, []JobSpec{spec}, NewStore(data))
	first, _, _ := r.Submit("margin", "t1", "run:1")
	r.update(first.ID, func(run *Run) { run.Status, run.StartedAt = "running", r.stamp() })
	r2, err := NewRunner(data, []JobSpec{spec}, NewStore(data))
	if err != nil {
		t.Fatal(err)
	}
	old, _ := r2.get(first.ID)
	if old.Status != "interrupted" || old.Error != "interrupted" || old.FinishedAt == "" {
		t.Fatalf("cut-short run: %+v", old)
	}
	retry := newestOf(t, r2, "t1")
	if retry.ID == first.ID || retry.Status != "queued" || retry.Attempt != 2 || retry.OccurrenceID != "run:1" {
		t.Fatalf("retry: %+v", retry)
	}
	if views := r2.Runs(); len(views) != 2 || views[0].ID != retry.ID {
		t.Fatalf("runs list: %+v", views)
	}
	stop := r2.Start()
	defer stop()
	if done := waitRun(t, r2, retry.ID); done.Status != "succeeded" {
		t.Fatalf("retry %+v", done)
	}
	if again, dup, err := r2.Submit("margin", "t1", "run:1"); err != nil || !dup || again.ID != retry.ID {
		t.Fatalf("redelivery after restart: %+v %v %v", again, dup, err)
	}
	if run, _ := r2.get(first.ID); run.Status != "interrupted" {
		t.Fatalf("interrupted run changed: %+v", run)
	}
}

func TestRunnerGivesUpAfterRepeatedRestarts(t *testing.T) {
	data, scripts := t.TempDir(), t.TempDir()
	spec := fakeJob(t, scripts, "margin", "", 0)
	r, _ := NewRunner(data, []JobSpec{spec}, NewStore(data))
	r.Submit("margin", "t1", "run:1")
	// Each restart interrupts the newest attempt while it is running.
	for i := 0; i < maxAttempts; i++ {
		cur := newestOf(t, r, "t1")
		r.update(cur.ID, func(run *Run) { run.Status = "running" })
		var err error
		if r, err = NewRunner(data, []JobSpec{spec}, NewStore(data)); err != nil {
			t.Fatal(err)
		}
	}
	runs := r.runsOf("margin")
	if len(runs) != maxAttempts {
		t.Fatalf("want %d attempts, got %d", maxAttempts, len(runs))
	}
	for _, run := range runs {
		if run.Status != "interrupted" || run.Error != "interrupted" {
			t.Fatalf("after %d interrupted attempts: %+v", maxAttempts, run)
		}
	}
}

func TestRestartsDoNotSpendAttemptsOfRunsThatNeverStarted(t *testing.T) {
	data, scripts := t.TempDir(), t.TempDir()
	spec := fakeJob(t, scripts, "margin", "", 0)
	r, _ := NewRunner(data, []JobSpec{spec}, NewStore(data))
	queued, _, _ := r.Submit("margin", "t1", "run:1")
	for i := 0; i < maxAttempts+2; i++ {
		var err error
		if r, err = NewRunner(data, []JobSpec{spec}, NewStore(data)); err != nil {
			t.Fatal(err)
		}
	}
	if run, _ := r.get(queued.ID); run.Status != "queued" || run.Attempt != 1 {
		t.Fatalf("queued run after restarts: %+v", run)
	}
}

func TestRunsViewHidesPlatformIdentity(t *testing.T) {
	data, scripts := t.TempDir(), t.TempDir()
	r, _ := NewRunner(data, []JobSpec{fakeJob(t, scripts, "margin", "", 0)}, NewStore(data))
	if _, _, err := r.Submit("margin", "secret-task-id", "run:1"); err != nil {
		t.Fatal(err)
	}
	for _, v := range r.Runs() {
		if strings.Contains(strings.ToLower(v.ID+v.Job+v.Error), "secret") {
			t.Fatalf("view leaks task identity: %+v", v)
		}
	}
}

func TestShutdownNeverFailsQueuedRuns(t *testing.T) {
	for round := 0; round < 20; round++ {
		data, scripts := t.TempDir(), t.TempDir()
		started := filepath.Join(scripts, "started")
		spec := scriptJob(t, scripts, "margin", "#!/bin/sh\ntouch '"+started+"'\nsleep 30\n", time.Minute)
		r, _ := NewRunner(data, []JobSpec{spec}, NewStore(data))
		var ids []string
		for i := 0; i < 4; i++ {
			run, _, err := r.Submit("margin", "t"+strconv.Itoa(i), "run:1")
			if err != nil {
				t.Fatal(err)
			}
			ids = append(ids, run.ID)
		}
		stop := r.Start()
		for i := 0; i < 200; i++ {
			if _, err := os.Stat(started); err == nil {
				break
			}
			time.Sleep(10 * time.Millisecond)
		}
		stop()
		for _, id := range ids {
			if run, _ := r.get(id); run.Status != "queued" && run.Status != "running" {
				t.Fatalf("round %d: shutdown left run %s as %s (%s)", round, id, run.Status, run.Error)
			}
		}
	}
}

func TestRetriedAttemptsKeepEarlierLogs(t *testing.T) {
	data, scripts := t.TempDir(), t.TempDir()
	spec := fakeJob(t, scripts, "margin", "", 0)
	r, _ := NewRunner(data, []JobSpec{spec}, NewStore(data))
	run, _, _ := r.Submit("margin", "t1", "run:1")
	logPath := filepath.Join(data, "runs", run.ID+".log")
	if err := os.WriteFile(logPath, []byte("first attempt output\n"), 0600); err != nil {
		t.Fatal(err)
	}
	r.update(run.ID, func(run *Run) { run.Status = "running" }) // cut short while running
	r2, _ := NewRunner(data, []JobSpec{spec}, NewStore(data))
	stop := r2.Start()
	defer stop()
	retry := newestOf(t, r2, "t1")
	waitRun(t, r2, retry.ID)
	first, _ := os.ReadFile(logPath)
	if !strings.Contains(string(first), "first attempt output") || !strings.Contains(string(first), "interrupted") {
		t.Fatalf("first log %q", first)
	}
	second, _ := os.ReadFile(filepath.Join(data, "runs", retry.ID+".log"))
	if !strings.Contains(string(second), "attempt 2") || !strings.Contains(string(second), run.ID) {
		t.Fatalf("retry log %q", second)
	}
}
