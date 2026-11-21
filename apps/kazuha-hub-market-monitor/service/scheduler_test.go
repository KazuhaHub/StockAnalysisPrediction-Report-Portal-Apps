package main

import (
	"fmt"
	"sort"
	"strings"
	"testing"
	"time"
)

var shanghai = func() *time.Location {
	loc, err := time.LoadLocation("Asia/Shanghai")
	if err != nil {
		panic(err)
	}
	return loc
}()

// at returns a Beijing-time instant in the week of Monday 2026-11-16.
func at(day time.Weekday, hh, mm int) time.Time {
	monday := time.Date(2026, 11, 16, 0, 0, 0, 0, shanghai)
	return monday.AddDate(0, 0, (int(day)+6)%7).Add(time.Duration(hh)*time.Hour + time.Duration(mm)*time.Minute)
}

func schedulerFor(t *testing.T, now *time.Time) (*Scheduler, *Runner) {
	t.Helper()
	data := t.TempDir()
	var specs []JobSpec
	for _, job := range []string{"marketdata", "sentiment", "panorama", "etf", "margin"} {
		specs = append(specs, JobSpec{Name: job, Command: []string{"/bin/true"}, Timeout: time.Minute})
	}
	r, err := NewRunner(data, specs, NewStore(data))
	if err != nil {
		t.Fatal(err)
	}
	r.now = func() time.Time { return now.UTC() }
	s := NewScheduler(r, DefaultSlots(), shanghai)
	s.now = func() time.Time { return *now }
	return s, r
}

func submitted(runs []Run) string {
	var out []string
	for _, r := range runs {
		out = append(out, r.Job)
	}
	return strings.Join(out, ",")
}

func TestSchedulerRunsEachSlotOnceWhenDue(t *testing.T) {
	now := at(time.Monday, 20, 59)
	s, _ := schedulerFor(t, &now)
	s.lastTick = now // already running before the slot: no catch-up
	if got := s.Tick(); len(got) != 0 {
		t.Fatalf("before 21:00: %s", submitted(got))
	}
	now = at(time.Monday, 21, 0).Add(30 * time.Second)
	if got := submitted(s.Tick()); got != "marketdata" {
		t.Fatalf("at 21:00: %q", got)
	}
	now = now.Add(time.Minute)
	if got := s.Tick(); len(got) != 0 {
		t.Fatalf("same slot submitted twice: %s", submitted(got))
	}
}

func TestSchedulerKeepsTheWeekdaysOfEachSlot(t *testing.T) {
	now := at(time.Sunday, 21, 1)
	s, _ := schedulerFor(t, &now)
	s.lastTick = at(time.Sunday, 20, 0)
	if got := s.Tick(); len(got) != 0 {
		t.Fatalf("Sunday evening: %s", submitted(got))
	}
	now = at(time.Saturday, 0, 41)
	s2, _ := schedulerFor(t, &now)
	s2.lastTick = at(time.Saturday, 0, 39)
	if got := submitted(s2.Tick()); got != "sentiment" {
		t.Fatalf("Saturday 00:41: %q", got)
	}
}

func TestSchedulerCatchesUpTheLastMissedSlotsOnStart(t *testing.T) {
	// Down from Monday afternoon until Tuesday 10:00: the latest occurrence
	// of each slot within the catch-up window runs once, oldest first.
	now := at(time.Tuesday, 10, 0)
	s, _ := schedulerFor(t, &now)
	got := submitted(s.Tick())
	if got != "marketdata,sentiment,panorama,etf,margin" {
		t.Fatalf("catch-up: %q", got)
	}
}

func TestSchedulerDoesNotCatchUpOldSlots(t *testing.T) {
	// Sunday 10:00: Saturday's 00:40/00:50 slots are over a day old.
	now := at(time.Sunday, 10, 0)
	s, _ := schedulerFor(t, &now)
	if got := s.Tick(); len(got) != 0 {
		t.Fatalf("stale catch-up: %s", submitted(got))
	}
}

func TestFallbackSlotRunsOnlyIfTheDaysPrimaryDidNotSucceed(t *testing.T) {
	cases := map[string]struct {
		status string
		want   string
	}{
		"primary succeeded":     {"succeeded", ""},
		"primary still running": {"running", ""},
		"primary failed":        {"failed", "margin"},
		"primary interrupted":   {"interrupted", "margin"},
	}
	for name, c := range cases {
		now := at(time.Monday, 9, 0).Add(10 * time.Second)
		s, r := schedulerFor(t, &now)
		s.lastTick = at(time.Monday, 8, 59)
		primary := s.Tick()
		if submitted(primary) != "margin" {
			t.Fatalf("%s: primary %q", name, submitted(primary))
		}
		r.update(primary[0].ID, func(run *Run) { run.Status = c.status })
		now = at(time.Monday, 9, 50).Add(10 * time.Second)
		if got := submitted(s.Tick()); got != c.want {
			t.Errorf("%s: fallback %q, want %q", name, got, c.want)
		}
	}
}

func TestSchedulerOccurrencesSurviveARestart(t *testing.T) {
	now := at(time.Monday, 21, 0).Add(30 * time.Second)
	s, r := schedulerFor(t, &now)
	s.lastTick = at(time.Monday, 20, 59)
	if got := submitted(s.Tick()); got != "marketdata" {
		t.Fatalf("first: %q", got)
	}
	// A new scheduler over the same runner (the service restarted) catches
	// up the day's other missed slots but does not submit 21:00 again.
	s2 := NewScheduler(r, DefaultSlots(), shanghai)
	s2.now = func() time.Time { return now }
	if got := submitted(s2.Tick()); strings.Contains(got, "marketdata") {
		t.Fatalf("after restart: %q", got)
	}
}

func TestDefaultSlotsMatchThePipelineTimers(t *testing.T) {
	var got []string
	for _, sl := range DefaultSlots() {
		var days []string
		for _, d := range sl.Days {
			days = append(days, d.String()[:3])
		}
		sort.Strings(days)
		got = append(got, sl.Job+" "+strings.Join(days, "")+" "+time.Date(0, 1, 1, sl.Hour, sl.Minute, 0, 0, time.UTC).Format("15:04"))
	}
	sort.Strings(got)
	want := []string{
		"etf FriSatThuTueWed 08:00",
		"margin FriMonThuTueWed 09:00",
		"margin FriMonThuTueWed 09:50",
		"marketdata FriMonThuTueWed 21:00",
		"marketdata FriMonThuTueWed 23:30",
		"panorama FriSatThuTueWed 00:50",
		"sentiment FriSatThuTueWed 00:40",
	}
	if strings.Join(got, "\n") != strings.Join(want, "\n") {
		t.Fatalf("slots:\n%s", strings.Join(got, "\n"))
	}
}

func TestSchedulerRetriesOccurrencesTheRunnerRefused(t *testing.T) {
	now := at(time.Monday, 20, 59)
	s, r := schedulerFor(t, &now)
	s.lastTick = now
	// Fill the queue so 21:00 is refused.
	for i := 0; i < cap(r.queue); i++ {
		if _, _, err := r.Submit("etf", fmt.Sprintf("fill/%d", i), fmt.Sprintf("run:%d", i)); err != nil {
			t.Fatal(err)
		}
	}
	now = at(time.Monday, 21, 0).Add(30 * time.Second)
	if got := s.Tick(); len(got) != 0 {
		t.Fatalf("queue full but submitted: %s", submitted(got))
	}
	// Drain the queue; a day later, Monday's 21:00 still runs, before
	// Tuesday's sentiment.
	for len(r.queue) > 0 {
		<-r.queue
	}
	now = at(time.Tuesday, 0, 41)
	if got := submitted(s.Tick()); got != "marketdata,sentiment" {
		t.Fatalf("after drain: %q", got)
	}
}

func TestFallbackSeesManualRunsOfTheDay(t *testing.T) {
	now := at(time.Monday, 22, 0)
	s, r := schedulerFor(t, &now)
	s.lastTick = at(time.Monday, 21, 59)
	manual, _, err := r.Submit("marketdata", "task-manual", "occ-manual")
	if err != nil {
		t.Fatal(err)
	}
	r.update(manual.ID, func(run *Run) { run.Status = "succeeded" })
	now = at(time.Monday, 23, 30).Add(10 * time.Second)
	if got := s.Tick(); len(got) != 0 {
		t.Fatalf("fallback after a successful manual run: %s", submitted(got))
	}
}

func TestCatchUpDoesNotRerunADecidedFallback(t *testing.T) {
	// 21:00 failed and the service went down before 23:30. Next morning the
	// 23:30 fallback is not caught up: sentiment and panorama follow anyway.
	now := at(time.Monday, 21, 0).Add(10 * time.Second)
	s, r := schedulerFor(t, &now)
	s.lastTick = at(time.Monday, 20, 59)
	primary := s.Tick()
	r.update(primary[0].ID, func(run *Run) { run.Status = "failed" })
	now = at(time.Tuesday, 10, 0)
	s2 := NewScheduler(r, DefaultSlots(), shanghai)
	s2.now = func() time.Time { return now }
	if got := submitted(s2.Tick()); strings.Contains(got, "marketdata") {
		t.Fatalf("catch-up reran marketdata: %q", got)
	}
}
