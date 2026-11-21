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

const catchUpWindow = 20 * time.Hour

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

type Scheduler struct {
	runner   *Runner
	slots    []Slot
	loc      *time.Location
	now      func() time.Time
	lastTick time.Time
	pending  []due
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
	s.lastTick = now
	return created
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
