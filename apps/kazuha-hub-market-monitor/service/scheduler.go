package main

import (
	"errors"
	"log"
	"sort"
	"strings"
	"time"
)

// The platform cannot yet originate tasks for a managed backend (its
// tasks/background route is not reachable from a networkless container), so
// the service keeps the pipeline's own timetable itself. Platform tasks to
// /v1/tasks/run remain a way to start a job by hand.
//
// Each slot occurrence becomes one run with the stable task ID
// "schedule/<job>/<YYYY-MM-DDTHH:MM>" in the schedule's time zone, so the run
// index deduplicates it across ticks and restarts. On start, the latest
// occurrence of each slot within catchUpWindow runs once if it never did,
// like systemd's Persistent=true. A fallback slot runs only when no run of
// the job queued earlier that day (scheduled or manual) succeeded or is still
// pending; on start it is not caught up if the job already ran that day, since
// the day's later jobs have used whatever that run produced. An occurrence the
// runner could not accept (queue full, index not saved) is retried on later
// ticks until it is accepted.
//
// A fresh or newly started installation must not sit empty until the next
// slot, so the first tick also bootstraps: every job whose output module has
// no installed snapshot, and that has no run queued or running and no
// occurrence that this tick really queues, gets one run with the task ID
// "bootstrap/<job>/<YYYY-MM-DD>" (the day in the schedule's zone). An
// occurrence whose run already failed queues nothing, so it does not hold a
// bootstrap back. The ID makes it at most one per job per day: a restart the
// same day does not repeat it and a failed bootstrap is not resubmitted that
// day; it is tried again only on the first tick after a process start on a
// later day. The marketdata job has no output module; it bootstraps when
// sentiment, panorama or margin, which read the bars it keeps, has no
// snapshot. On the timetable marketdata (21:00) runs before the next
// morning's margin (09:00), and the single worker runs a margin queued while
// marketdata is still running after it.
// Marketdata is queued first, then the caught-up occurrences, then the other
// bootstraps in timetable order (sentiment, panorama, etf, margin); the runner
// works the queue one job at a time in that order. A bootstrap the runner
// could not accept is retried on later ticks under the day it was decided on,
// after checking again that the snapshot is still missing and no run of the
// job is queued or running.

const (
	catchUpWindow = 20 * time.Hour
	// scheduleZone is the time zone of every slot: exchange time.
	scheduleZone = "Asia/Shanghai"
)

type Slot struct {
	Job          string
	Days         []time.Weekday
	Hour, Minute int
	Fallback     bool
}

var (
	weekdays = []time.Weekday{time.Monday, time.Tuesday, time.Wednesday, time.Thursday, time.Friday}
	// Tuesday to Saturday: the jobs that report on the previous trading day.
	dayAfter = []time.Weekday{time.Tuesday, time.Wednesday, time.Thursday, time.Friday, time.Saturday}
)

// DefaultSlots is the pipeline's timetable (its systemd timers), in Beijing
// time.
func DefaultSlots() []Slot {
	return []Slot{
		{Job: "marketdata", Days: weekdays, Hour: 21},
		{Job: "marketdata", Days: weekdays, Hour: 23, Minute: 30, Fallback: true},
		{Job: "sentiment", Days: dayAfter, Hour: 0, Minute: 40},
		{Job: "panorama", Days: dayAfter, Hour: 0, Minute: 50},
		{Job: "etf", Days: dayAfter, Hour: 8},
		{Job: "margin", Days: weekdays, Hour: 9},
		{Job: "margin", Days: weekdays, Hour: 9, Minute: 50, Fallback: true},
	}
}

// bootstrapJobs lists the jobs in dependency order, with the module each one
// produces. Marketdata updates the bar store that sentiment, panorama and
// margin read, so it goes first; etf fetches its own inputs.
var bootstrapJobs = []struct{ job, module string }{
	{"marketdata", ""},
	{"sentiment", "sentiment"},
	{"panorama", "panorama"},
	{"etf", "etf"},
	{"margin", "margin"},
}

// barConsumers are the modules whose jobs read what marketdata produces.
var barConsumers = []string{"sentiment", "panorama", "margin"}

type pendingBoot struct{ job, day string }

type Scheduler struct {
	runner   *Runner
	slots    []Slot
	loc      *time.Location
	now      func() time.Time
	lastTick time.Time
	pending  []due
	// pendingBootstrap holds bootstraps the runner could not accept yet, each
	// with the day it was decided on.
	pendingBootstrap []pendingBoot
}

func NewScheduler(r *Runner, slots []Slot, loc *time.Location) *Scheduler {
	return &Scheduler{runner: r, slots: slots, loc: loc, now: time.Now}
}

func (sl Slot) on(day time.Weekday) bool {
	for _, d := range sl.Days {
		if d == day {
			return true
		}
	}
	return false
}

// latest returns the slot's most recent occurrence in (after, until].
func (sl Slot) latest(after, until time.Time, loc *time.Location) (time.Time, bool) {
	u := until.In(loc)
	for back := 0; back <= 8; back++ {
		day := u.AddDate(0, 0, -back)
		t := time.Date(day.Year(), day.Month(), day.Day(), sl.Hour, sl.Minute, 0, 0, loc)
		if t.After(until) || !sl.on(t.Weekday()) {
			continue
		}
		if t.After(after) {
			return t, true
		}
		return time.Time{}, false
	}
	return time.Time{}, false
}

// next returns the slot's first occurrence strictly after t.
func (sl Slot) next(t time.Time, loc *time.Location) (time.Time, bool) {
	u := t.In(loc)
	for ahead := 0; ahead <= 8; ahead++ {
		day := u.AddDate(0, 0, ahead)
		c := time.Date(day.Year(), day.Month(), day.Day(), sl.Hour, sl.Minute, 0, 0, loc)
		if c.After(t) && sl.on(c.Weekday()) {
			return c, true
		}
	}
	return time.Time{}, false
}

func taskID(job string, t time.Time) string {
	return "schedule/" + job + "/" + t.Format("2006-01-02T15:04")
}

// skipFallback reports whether the fallback occurrence at t should not run:
// a run of the job queued earlier that day succeeded or is pending, or, when
// catching up, the job ran at all that day.
func (s *Scheduler) skipFallback(job string, t time.Time, catchUp bool) bool {
	day := time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, s.loc)
	for _, run := range s.runner.runsOf(job) {
		q, ok := s.runTime(run)
		if !ok || q.Before(day) || !q.Before(t) {
			continue
		}
		if catchUp {
			return true
		}
		switch run.Status {
		case "succeeded", "queued", "running":
			return true
		}
	}
	return false
}

// runTime is when a run counts as having been started: a scheduled run at
// its occurrence (a caught-up run is queued later than that), any other run
// when it was queued.
func (s *Scheduler) runTime(run Run) (time.Time, bool) {
	if rest, ok := strings.CutPrefix(run.TaskID, "schedule/"+run.Job+"/"); ok {
		t, err := time.ParseInLocation("2006-01-02T15:04", rest, s.loc)
		return t, err == nil
	}
	t, err := time.Parse(time.RFC3339Nano, run.QueuedAt)
	return t, err == nil
}

type due struct {
	slot Slot
	at   time.Time
}

// Tick submits every occurrence that became due since the previous tick (on
// the first tick: the latest occurrence of each slot within catchUpWindow)
// and returns the runs it created, oldest occurrence first.
func (s *Scheduler) Tick() []Run {
	now := s.now()
	catchUp := s.lastTick.IsZero()
	after := s.lastTick
	if catchUp {
		after = now.Add(-catchUpWindow)
	}
	dues := s.pending
	s.pending = nil
	for _, sl := range s.slots {
		if t, ok := sl.latest(after, now, s.loc); ok {
			dues = append(dues, due{sl, t})
		}
	}
	sort.SliceStable(dues, func(i, j int) bool { return dues[i].at.Before(dues[j].at) })
	var created []Run
	day := now.In(s.loc).Format("2006-01-02")
	var first, last []pendingBoot
	retry := s.pendingBootstrap
	s.pendingBootstrap = nil
	if catchUp {
		// Jobs whose occurrence this tick really queues a run are not
		// bootstrapped as well: an occurrence with no run yet, or whose run
		// succeeded or is pending. A failed existing run queues nothing, so
		// it does not count, and a fallback counts only if it would run.
		scheduled := map[string]bool{}
		for _, d := range dues {
			if d.slot.Fallback && s.skipFallback(d.slot.Job, d.at, true) {
				continue
			}
			if run, ok := s.runner.byTaskID(taskID(d.slot.Job, d.at)); ok {
				switch run.Status {
				case "succeeded", "queued", "running":
				default:
					continue
				}
			}
			scheduled[d.slot.Job] = true
		}
		for _, job := range s.bootstrapDue(scheduled) {
			if job == "marketdata" {
				first = append(first, pendingBoot{job, day})
			} else {
				last = append(last, pendingBoot{job, day})
			}
		}
	} else {
		last = retry
	}
	s.bootstrap(first, &created)
	for _, d := range dues {
		if d.slot.Fallback && s.skipFallback(d.slot.Job, d.at, catchUp) {
			continue
		}
		run, duplicate, err := s.runner.Submit(d.slot.Job, taskID(d.slot.Job, d.at), "run:"+d.at.Format("2006-01-02T15:04"))
		switch {
		case errors.Is(err, errConflict), errors.Is(err, errUnknownJob):
			log.Printf("schedule %s at %s: %v", d.slot.Job, d.at.Format(time.RFC3339), err)
		case err != nil:
			// Queue full or the run index not saved: try again next tick.
			s.pending = append(s.pending, d)
		case !duplicate:
			created = append(created, run)
		}
	}
	s.bootstrap(last, &created)
	s.lastTick = now
	return created
}

// bootstrapDue lists, in dependency order, the jobs that need a bootstrap
// run: no snapshot of their module, no run queued or running, and not among
// the jobs already being caught up on this tick.
func (s *Scheduler) bootstrapDue(scheduled map[string]bool) []string {
	var jobs []string
	for _, b := range bootstrapJobs {
		if !scheduled[b.job] && s.bootstrapNeeded(b.job) {
			jobs = append(jobs, b.job)
		}
	}
	return jobs
}

// bootstrapNeeded reports whether the job's output is missing from the store
// and no run of the job is queued or running.
func (s *Scheduler) bootstrapNeeded(job string) bool {
	if s.active(job) {
		return false
	}
	missing := func(module string) bool {
		dates, err := s.runner.store.Dates(module)
		if err != nil {
			log.Printf("bootstrap: reading %s snapshots: %v", module, err)
			return false // unknown: do not queue work on a guess
		}
		return len(dates) == 0
	}
	if job == "marketdata" {
		for _, m := range barConsumers {
			if missing(m) {
				return true
			}
		}
		return false
	}
	for _, b := range bootstrapJobs {
		if b.job == job {
			return missing(b.module)
		}
	}
	return false
}

// active reports whether a run of the job is queued or running.
func (s *Scheduler) active(job string) bool {
	for _, run := range s.runner.runsOf(job) {
		if run.Status == "queued" || run.Status == "running" {
			return true
		}
	}
	return false
}

// bootstrap submits one run per job under the task ID of the day it was
// decided on. A job the runner could not accept is kept for the next tick,
// which checks again that it is still needed.
func (s *Scheduler) bootstrap(jobs []pendingBoot, created *[]Run) {
	for i, b := range jobs {
		if !s.bootstrapNeeded(b.job) {
			continue
		}
		run, duplicate, err := s.runner.Submit(b.job, "bootstrap/"+b.job+"/"+b.day, "bootstrap:"+b.day)
		switch {
		case errors.Is(err, errConflict), errors.Is(err, errUnknownJob):
			log.Printf("bootstrap %s on %s: %v", b.job, b.day, err)
		case err != nil:
			s.pendingBootstrap = append(s.pendingBootstrap, jobs[i:]...)
			return
		case !duplicate:
			*created = append(*created, run)
		}
	}
}

// Start ticks every 30 seconds until the returned function is called.
func (s *Scheduler) Start() func() {
	stop := make(chan struct{})
	done := make(chan struct{})
	go func() {
		defer close(done)
		s.Tick()
		ticker := time.NewTicker(30 * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-stop:
				return
			case <-ticker.C:
				s.Tick()
			}
		}
	}()
	return func() { close(stop); <-done }
}
