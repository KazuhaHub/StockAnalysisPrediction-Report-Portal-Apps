package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

// The background task queue. Portal gives one task execution 45 seconds, so a
// handler may only validate, record the work and answer; the work itself runs
// here, outside the request. Each accepted occurrence is one file under
// <data>/queue: name.json is pending, name.done is finished. A repeat of an
// occurrence (Portal sends the same one again after a retry answer, a restore
// or an operator action) is therefore a duplicate and does not run twice.
//
// A job runs at least once: work still pending at a restart is queued again, so
// a handler must be idempotent. A job whose handler fails stays pending. It is
// tried again at the next start, or when the same occurrence is submitted again;
// add a retry policy of your own if the work needs one.
//
// Nothing is written until the first task arrives (the descriptor promises
// writes_on_startup false), so a read-only /data only fails the submit.

var (
	errUnknownJob = errors.New("unknown job")
	errConflict   = errors.New("occurrence reused for another job")
	errQueueFull  = errors.New("queue full")
)

const (
	// queueCapacity bounds the accepted work not yet finished. Work recovered at
	// a start is kept whatever its size; the bound only refuses new submissions.
	queueCapacity = 32
	// doneRetention is how long a finished occurrence is remembered for duplicate detection.
	doneRetention = 7 * 24 * time.Hour
)

// Job is one unit of accepted work.
type Job struct {
	Name         string `json:"job"`
	TaskID       string `json:"task_id"`
	OccurrenceID string `json:"occurrence_id"`
}

// jobs lists the work this app can do. Replace "example" with your own
// handlers; keep them idempotent and bounded.
var jobs = map[string]func(context.Context, Job) error{
	"example": func(context.Context, Job) error { return nil },
}

type Queue struct {
	dir string
	run map[string]func(context.Context, Job) error

	mu       sync.Mutex
	waiting  []Job
	inflight map[string]bool // occurrence IDs that are waiting or running
	wake     chan struct{}
}

func NewQueue(dataDir string, run map[string]func(context.Context, Job) error) (*Queue, error) {
	return &Queue{dir: filepath.Join(dataDir, "queue"), run: run, inflight: map[string]bool{}, wake: make(chan struct{}, 1)}, nil
}

func (q *Queue) path(occurrence, suffix string) string {
	sum := sha256.Sum256([]byte(occurrence))
	return filepath.Join(q.dir, hex.EncodeToString(sum[:])+suffix)
}

func (q *Queue) enqueue(job Job) {
	q.inflight[job.OccurrenceID] = true
	q.waiting = append(q.waiting, job)
	select {
	case q.wake <- struct{}{}:
	default:
	}
}

// Submit records the job and queues it. It never runs the work. duplicate is
// true when the same occurrence for the same job was accepted before.
func (q *Queue) Submit(name, taskID, occurrence string) (duplicate bool, err error) {
	if _, ok := q.run[name]; !ok {
		return false, errUnknownJob
	}
	q.mu.Lock()
	defer q.mu.Unlock()
	for _, suffix := range []string{".json", ".done"} {
		raw, err := os.ReadFile(q.path(occurrence, suffix))
		if err != nil {
			continue
		}
		var seen Job
		if json.Unmarshal(raw, &seen) != nil || seen.Name != name {
			return false, errConflict
		}
		if suffix == ".json" && !q.inflight[occurrence] {
			// Accepted earlier and not running: its handler failed. Try it again.
			q.enqueue(seen)
		}
		return true, nil
	}
	if len(q.inflight) >= queueCapacity {
		return false, errQueueFull
	}
	if err := os.MkdirAll(q.dir, 0o700); err != nil {
		return false, err
	}
	job := Job{Name: name, TaskID: taskID, OccurrenceID: occurrence}
	raw, _ := json.Marshal(job)
	// Write the whole record, then publish it with a rename, so a crash never
	// leaves a half-written occurrence that would block its retry.
	tmp, err := os.CreateTemp(q.dir, "tmp-*")
	if err != nil {
		return false, err
	}
	_, werr := tmp.Write(raw)
	cerr := tmp.Close()
	if werr != nil || cerr != nil {
		os.Remove(tmp.Name())
		return false, errors.Join(werr, cerr)
	}
	if err := os.Rename(tmp.Name(), q.path(occurrence, ".json")); err != nil {
		os.Remove(tmp.Name())
		return false, err
	}
	q.enqueue(job)
	return false, nil
}

// Start queues work that was pending at the last stop, forgets old finished
// occurrences and runs the worker. The returned function stops it and waits for
// the job in flight.
func (q *Queue) Start() (stop func()) {
	q.mu.Lock()
	entries, _ := os.ReadDir(q.dir)
	for _, entry := range entries {
		path := filepath.Join(q.dir, entry.Name())
		info, err := entry.Info()
		switch {
		case err != nil:
		case strings.HasPrefix(entry.Name(), "tmp-") || (strings.HasSuffix(entry.Name(), ".done") && time.Since(info.ModTime()) > doneRetention):
			os.Remove(path) // a crashed write, or an occurrence too old to see again
		case strings.HasSuffix(entry.Name(), ".json"):
			raw, err := os.ReadFile(path)
			var job Job
			if err == nil && json.Unmarshal(raw, &job) == nil && q.run[job.Name] != nil && !q.inflight[job.OccurrenceID] {
				q.enqueue(job)
			}
		}
	}
	q.mu.Unlock()
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		defer close(done)
		for ctx.Err() == nil {
			q.mu.Lock()
			var job Job
			have := len(q.waiting) > 0
			if have {
				job, q.waiting = q.waiting[0], q.waiting[1:]
			}
			q.mu.Unlock()
			if !have {
				select {
				case <-ctx.Done():
				case <-q.wake:
				}
				continue
			}
			ok := q.run[job.Name](ctx, job) == nil
			q.mu.Lock()
			delete(q.inflight, job.OccurrenceID)
			q.mu.Unlock()
			if ok {
				_ = os.Rename(q.path(job.OccurrenceID, ".json"), q.path(job.OccurrenceID, ".done"))
			}
		}
	}()
	return func() { cancel(); <-done }
}
