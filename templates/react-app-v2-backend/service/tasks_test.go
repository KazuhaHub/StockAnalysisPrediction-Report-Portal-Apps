package main

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strconv"
	"sync/atomic"
	"testing"
	"time"
)

func recorder() (map[string]func(context.Context, Job) error, chan Job) {
	ran := make(chan Job, 128)
	return map[string]func(context.Context, Job) error{
		"ok":   func(_ context.Context, j Job) error { ran <- j; return nil },
		"fail": func(_ context.Context, j Job) error { ran <- j; return errors.New("later") },
	}, ran
}

func waitJob(t *testing.T, ran chan Job) Job {
	t.Helper()
	select {
	case j := <-ran:
		return j
	case <-time.After(5 * time.Second):
		t.Fatal("job did not run")
		return Job{}
	}
}

func waitFile(t *testing.T, path string) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for {
		if _, err := os.Stat(path); err == nil {
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("%s did not appear", path)
		}
		time.Sleep(10 * time.Millisecond)
	}
}

func TestQueueRunsAcceptedWorkOnce(t *testing.T) {
	run, ran := recorder()
	q, _ := NewQueue(t.TempDir(), run)
	stop := q.Start()
	defer stop()
	if dup, err := q.Submit("ok", "t1", "occ-1"); dup || err != nil {
		t.Fatalf("dup %v err %v", dup, err)
	}
	if j := waitJob(t, ran); j.OccurrenceID != "occ-1" {
		t.Fatalf("job %+v", j)
	}
	// Once finished the occurrence stays known, so a late redelivery is a duplicate and does not run again.
	waitFile(t, q.path("occ-1", ".done"))
	if dup, err := q.Submit("ok", "t1", "occ-1"); !dup || err != nil {
		t.Fatalf("redelivery: dup %v err %v", dup, err)
	}
	select {
	case j := <-ran:
		t.Fatalf("ran twice: %+v", j)
	case <-time.After(100 * time.Millisecond):
	}
}

func TestQueueRefusesUnknownJobsConflictsAndOverflow(t *testing.T) {
	run, _ := recorder()
	q, _ := NewQueue(t.TempDir(), run)
	if _, err := q.Submit("nope", "t", "a"); !errors.Is(err, errUnknownJob) {
		t.Fatalf("unknown: %v", err)
	}
	if _, err := q.Submit("ok", "t", "a"); err != nil {
		t.Fatal(err)
	}
	if _, err := q.Submit("fail", "t", "a"); !errors.Is(err, errConflict) {
		t.Fatalf("conflict: %v", err)
	}
	for i := 1; i < queueCapacity; i++ {
		if _, err := q.Submit("ok", "t", "occ-"+strconv.Itoa(i)); err != nil {
			t.Fatalf("%d: %v", i, err)
		}
	}
	if _, err := q.Submit("ok", "t", "one-too-many"); !errors.Is(err, errQueueFull) {
		t.Fatalf("overflow: %v", err)
	}
	if _, err := os.Stat(q.path("one-too-many", ".json")); err == nil {
		t.Fatal("a refused occurrence was recorded")
	}
}

func TestAFailedJobStaysPendingAndRunsAgainWhenSubmittedAgain(t *testing.T) {
	var attempts atomic.Int32
	ran := make(chan Job, 4)
	run := map[string]func(context.Context, Job) error{"flaky": func(_ context.Context, j Job) error {
		ran <- j
		if attempts.Add(1) == 1 {
			return errors.New("first attempt fails")
		}
		return nil
	}}
	q, _ := NewQueue(t.TempDir(), run)
	stop := q.Start()
	defer stop()
	if _, err := q.Submit("flaky", "t", "occ"); err != nil {
		t.Fatal(err)
	}
	waitJob(t, ran)
	// Wait until the worker has let go of the failed job.
	deadline := time.Now().Add(5 * time.Second)
	for {
		q.mu.Lock()
		busy := q.inflight["occ"]
		q.mu.Unlock()
		if !busy {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("job never finished")
		}
		time.Sleep(5 * time.Millisecond)
	}
	if _, err := os.Stat(q.path("occ", ".json")); err != nil {
		t.Fatalf("a failed job is no longer pending: %v", err)
	}
	// The same occurrence again is a duplicate of accepted work, and it is queued again, not lost.
	if dup, err := q.Submit("flaky", "t", "occ"); !dup || err != nil {
		t.Fatalf("dup %v err %v", dup, err)
	}
	waitJob(t, ran)
	waitFile(t, q.path("occ", ".done"))
}

func TestPendingWorkSurvivesARestartAndIsNotLimitedByTheCapacity(t *testing.T) {
	dir := t.TempDir()
	run, ran := recorder()
	first, _ := NewQueue(dir, run)
	total := queueCapacity + 8
	for i := 0; i < total; i++ {
		occurrence := "occ-" + strconv.Itoa(i)
		if i < queueCapacity {
			if _, err := first.Submit("ok", "t", occurrence); err != nil {
				t.Fatal(err)
			}
			continue
		}
		raw, _ := json.Marshal(Job{Name: "ok", TaskID: "t", OccurrenceID: occurrence})
		if err := os.WriteFile(first.path(occurrence, ".json"), raw, 0o600); err != nil {
			t.Fatal(err)
		}
	}
	// A new process: the first queue never ran anything.
	second, _ := NewQueue(dir, run)
	stop := second.Start()
	defer stop()
	seen := map[string]bool{}
	for i := 0; i < total; i++ {
		seen[waitJob(t, ran).OccurrenceID] = true
	}
	if len(seen) != total {
		t.Fatalf("ran %d of %d", len(seen), total)
	}
}

func TestNothingIsWrittenUntilATaskArrives(t *testing.T) {
	dir := t.TempDir()
	run, _ := recorder()
	q, _ := NewQueue(dir, run)
	stop := q.Start()
	stop()
	if entries, _ := os.ReadDir(dir); len(entries) != 0 {
		t.Fatalf("start wrote %v", entries)
	}
}

func TestStartForgetsOldFinishedOccurrencesAndCrashedWrites(t *testing.T) {
	dir := t.TempDir()
	run, _ := recorder()
	q, _ := NewQueue(dir, run)
	if err := os.MkdirAll(q.dir, 0o700); err != nil {
		t.Fatal(err)
	}
	old, fresh, tmp := q.path("old", ".done"), q.path("fresh", ".done"), filepath.Join(q.dir, "tmp-123")
	for _, p := range []string{old, fresh, tmp} {
		if err := os.WriteFile(p, []byte("{}"), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	past := time.Now().Add(-doneRetention - time.Hour)
	if err := os.Chtimes(old, past, past); err != nil {
		t.Fatal(err)
	}
	q.Start()()
	for p, want := range map[string]bool{old: false, fresh: true, tmp: false} {
		if _, err := os.Stat(p); (err == nil) != want {
			t.Errorf("%s present=%v want %v", filepath.Base(p), err == nil, want)
		}
	}
}
