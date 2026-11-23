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

// schedulerFor builds a scheduler over a store that already holds a snapshot
// of every job's module, so only the timetable is under test.
func schedulerFor(t *testing.T, now *time.Time) (*Scheduler, *Runner) {
	t.Helper()
	s, r := emptyStoreSchedulerFor(t, now)
	for _, module := range []string{"sentiment", "panorama", "etf", "margin"} {
		installTest(t, r.store, module, "2026-11-13")
	}
	return s, r
}

// emptyStoreSchedulerFor is a scheduler over a store with no snapshots.
func emptyStoreSchedulerFor(t *testing.T, now *time.Time) (*Scheduler, *Runner) {
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

const bootstrapOrder = "marketdata,sentiment,panorama,etf,margin"

func TestBootstrapSubmitsEachJobOfAnEmptyStoreInDependencyOrder(t *testing.T) {
	// Sunday: no slot is within the catch-up window, so only bootstraps run.
	now := at(time.Sunday, 10, 0)
	s, r := emptyStoreSchedulerFor(t, &now)
	got := s.Tick()
	if submitted(got) != bootstrapOrder {
		t.Fatalf("bootstrap: %q", submitted(got))
	}
	for _, run := range got {
		if run.TaskID != "bootstrap/"+run.Job+"/2026-11-22" {
			t.Errorf("task ID %q", run.TaskID)
		}
	}
	// One worker, FIFO: the queue holds the five in that order.
	var queued []string
	for len(r.queue) > 0 {
		id := <-r.queue
		run, _ := r.get(id)
		queued = append(queued, run.Job)
	}
	if strings.Join(queued, ",") != bootstrapOrder {
		t.Fatalf("queue order: %v", queued)
	}
	// Later ticks submit nothing more.
	now = now.Add(time.Minute)
	if more := s.Tick(); len(more) != 0 {
		t.Fatalf("second tick: %s", submitted(more))
	}
}

func TestBootstrapSkipsJobsThatHaveSnapshots(t *testing.T) {
	now := at(time.Sunday, 10, 0)
	s, _ := schedulerFor(t, &now) // every module installed
	if got := s.Tick(); len(got) != 0 {
		t.Fatalf("bootstrap with snapshots: %s", submitted(got))
	}
	// Only sentiment and margin missing: those two, plus marketdata, which
	// sentiment reads.
	now = at(time.Sunday, 10, 0)
	s2, r := emptyStoreSchedulerFor(t, &now)
	installTest(t, r.store, "panorama", "2026-11-13")
	installTest(t, r.store, "etf", "2026-11-13")
	if got := submitted(s2.Tick()); got != "marketdata,sentiment,margin" {
		t.Fatalf("partial store: %q", got)
	}
	// Only margin missing: margin and etf read no bars, so no marketdata.
	s3, r3 := emptyStoreSchedulerFor(t, &now)
	for _, m := range []string{"sentiment", "panorama", "etf"} {
		installTest(t, r3.store, m, "2026-11-13")
	}
	if got := submitted(s3.Tick()); got != "margin" {
		t.Fatalf("margin only: %q", got)
	}
}

func TestBootstrapIsNotRepeatedAfterARestartTheSameDay(t *testing.T) {
	now := at(time.Sunday, 10, 0)
	s, r := emptyStoreSchedulerFor(t, &now)
	if got := s.Tick(); len(got) != 5 {
		t.Fatalf("first: %s", submitted(got))
	}
	// Still queued: nothing to add.
	s2 := NewScheduler(r, DefaultSlots(), shanghai)
	s2.now = func() time.Time { return now.Add(time.Hour) }
	if got := s2.Tick(); len(got) != 0 {
		t.Fatalf("restart with runs queued: %s", submitted(got))
	}
	// Finished without a snapshot (failed): still not repeated that day.
	for _, run := range r.Runs() {
		r.update(run.ID, func(run *Run) { run.Status = "failed" })
	}
	s3 := NewScheduler(r, DefaultSlots(), shanghai)
	s3.now = func() time.Time { return at(time.Sunday, 23, 0) }
	if got := s3.Tick(); len(got) != 0 {
		t.Fatalf("failed bootstrap resubmitted the same day: %s", submitted(got))
	}
	// The next day's start tries again.
	s4 := NewScheduler(r, DefaultSlots(), shanghai)
	s4.now = func() time.Time { return at(time.Sunday, 8, 0).Add(24 * time.Hour) }
	got := s4.Tick()
	if submitted(got) != bootstrapOrder || got[0].TaskID != "bootstrap/marketdata/2026-11-23" {
		t.Fatalf("next day: %q", submitted(got))
	}
}

func TestBootstrapDoesNotRetryAFailedBootstrapInALoop(t *testing.T) {
	now := at(time.Sunday, 10, 0)
	s, r := emptyStoreSchedulerFor(t, &now)
	for _, run := range s.Tick() {
		r.update(run.ID, func(run *Run) { run.Status = "failed" })
	}
	for i := 0; i < 5; i++ {
		now = now.Add(30 * time.Second)
		if got := s.Tick(); len(got) != 0 {
			t.Fatalf("tick %d: %s", i, submitted(got))
		}
	}
}

func TestBootstrapSkipsAJobWithAQueuedOrRunningRun(t *testing.T) {
	now := at(time.Sunday, 10, 0)
	s, r := emptyStoreSchedulerFor(t, &now)
	for i, job := range []string{"etf", "margin"} {
		run, _, err := r.Submit(job, "task-manual-"+job, "occ")
		if err != nil {
			t.Fatal(err)
		}
		if i == 1 {
			r.update(run.ID, func(run *Run) { run.Status = "running" })
		}
	}
	if got := submitted(s.Tick()); got != "marketdata,sentiment,panorama" {
		t.Fatalf("with etf queued and margin running: %q", got)
	}
}

func TestBootstrapSkipsAJobThatCaughtUpAScheduledRun(t *testing.T) {
	// Tuesday 10:00 catches up every slot's latest occurrence; the empty
	// store would otherwise want a second run of each.
	now := at(time.Tuesday, 10, 0)
	s, _ := emptyStoreSchedulerFor(t, &now)
	got := s.Tick()
	if submitted(got) != bootstrapOrder {
		t.Fatalf("catch-up only: %q", submitted(got))
	}
	for _, run := range got {
		if !strings.HasPrefix(run.TaskID, "schedule/") {
			t.Errorf("%s ran as %q, want a scheduled occurrence", run.Job, run.TaskID)
		}
	}
	// Monday 10:00 catches up only margin's 09:00 slot; the other jobs are
	// not due and bootstrap, marketdata first.
	now = at(time.Monday, 10, 0)
	s2, _ := emptyStoreSchedulerFor(t, &now)
	var ids []string
	for _, run := range s2.Tick() {
		ids = append(ids, run.Job+":"+strings.SplitN(run.TaskID, "/", 2)[0])
	}
	want := "marketdata:bootstrap,margin:schedule,sentiment:bootstrap,panorama:bootstrap,etf:bootstrap"
	if strings.Join(ids, ",") != want {
		t.Fatalf("monday: %v", ids)
	}
}

func TestBootstrapRunsBeforeTheCaughtUpJobsThatReadItsData(t *testing.T) {
	// Monday 10:00 with only panorama missing: panorama bootstraps after
	// marketdata; the caught-up margin run does not jump the order.
	now := at(time.Monday, 10, 0)
	s, r := emptyStoreSchedulerFor(t, &now)
	for _, m := range []string{"sentiment", "etf", "margin"} {
		installTest(t, r.store, m, "2026-11-13")
	}
	if got := submitted(s.Tick()); got != "marketdata,margin,panorama" {
		t.Fatalf("order: %q", got)
	}
}

func TestBootstrapRetriesWhenTheQueueIsFull(t *testing.T) {
	now := at(time.Sunday, 10, 0)
	s, r := emptyStoreSchedulerFor(t, &now)
	for i := 0; i < cap(r.queue); i++ {
		if _, _, err := r.Submit("etf", fmt.Sprintf("fill/%d", i), fmt.Sprintf("run:%d", i)); err != nil {
			t.Fatal(err)
		}
	}
	if got := s.Tick(); len(got) != 0 {
		t.Fatalf("queue full but submitted: %s", submitted(got))
	}
	for len(r.queue) > 0 {
		<-r.queue
	}
	for _, run := range r.Runs() {
		r.update(run.ID, func(run *Run) { run.Status = "succeeded" })
	}
	now = now.Add(30 * time.Second)
	// etf is missing from the retry: the filler runs made it "active" when
	// the bootstrap was decided, and that decision stands.
	if got := submitted(s.Tick()); got != "marketdata,sentiment,panorama,margin" {
		t.Fatalf("after drain: %q", got)
	}
}
