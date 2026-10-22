package status

import (
	"fmt"
	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
	"testing"
	"time"
)

func TestRetroactiveMaintenanceReconcilesFullHourAndMissingEvidence(t *testing.T) {
	s := testStore(t)
	start := time.Now().UTC().Truncate(time.Hour).Add(-3 * time.Hour)
	c, id := seedHistoryMonitor(t, s, start)
	for minute := 1; minute <= 61; minute += 2 {
		historySample(t, s, id, start.Add(time.Duration(minute)*time.Minute))
	}
	admin := protocol.Viewer{Subject: "admin", Role: "admin"}
	before, err := s.History(admin, c.ID, start, start.Add(time.Hour))
	if err != nil || len(before) != 1 || before[0].OperationalMS == 0 {
		t.Fatalf("fixture=%+v %v", before, err)
	}
	if err := s.SaveMaintenance(admin, MaintenanceInput{ComponentID: c.ID, StartsAt: start.Add(10 * time.Minute).Format(time.RFC3339), EndsAt: start.Add(20 * time.Minute).Format(time.RFC3339), Summary: "Recorded maintenance"}); err != nil {
		t.Fatal(err)
	}
	after, err := s.History(admin, c.ID, start, start.Add(time.Hour))
	if err != nil || len(after) != 1 || after[0].ExcludedMS != 600000 || after[0].OperationalMS >= before[0].OperationalMS {
		t.Fatalf("full hour ignored retrospective maintenance: before=%+v after=%+v err=%v", before, after, err)
	}
	// Once raw evidence has expired, retain exact exclusions and report the rest
	// unknown rather than allocating an old aggregate proportionally.
	if _, err := s.db.Exec(`DELETE FROM observations WHERE monitor_id=?`, id); err != nil {
		t.Fatal(err)
	}
	after, err = s.History(admin, c.ID, start, start.Add(time.Hour))
	if err != nil || len(after) != 1 || after[0].OperationalMS != 0 || after[0].ExcludedMS != 600000 || after[0].UnknownMS != 3000000 {
		t.Fatalf("expired evidence fabricated history=%+v err=%v", after, err)
	}
}

func TestCleanupKeepsAggregateOverlappingRetentionBoundary(t *testing.T) {
	s := testStore(t)
	start := time.Now().UTC().Truncate(time.Hour).Add(-100 * 24 * time.Hour)
	_, id := seedHistoryMonitor(t, s, start)
	cleanupAt := start.Add(90*24*time.Hour + 30*time.Minute)
	if _, err := s.db.Exec(`INSERT INTO hourly_aggregates VALUES(?,?,60000,0,0,3540000,0)`, id, start.UnixMilli()); err != nil {
		t.Fatal(err)
	}
	if err := s.Cleanup(cleanupAt); err != nil {
		t.Fatal(err)
	}
	var count int
	s.db.QueryRow(`SELECT COUNT(*) FROM hourly_aggregates WHERE monitor_id=? AND hour_at=?`, id, start.UnixMilli()).Scan(&count)
	if count != 1 {
		t.Fatal("cleanup removed hour overlapping retained range")
	}
}

func TestRetrospectiveHistoryHandlesMoreThanOneBucketOfRawEvidence(t *testing.T) {
	s := testStore(t)
	start := time.Now().UTC().Truncate(time.Hour).Add(-48 * time.Hour)
	c, id := seedHistoryMonitor(t, s, start)
	tx, err := s.db.Begin()
	if err != nil {
		t.Fatal(err)
	}
	last := ""
	for i := 1; i <= 2000; i++ {
		at := start.Add(time.Duration(i) * 30 * time.Second).UnixMilli()
		last = newID()
		metadata := fmt.Sprintf(`{"_status":{"version":1,"state":"operational","fresh_until":%d}}`, at+180000)
		if _, err := tx.Exec(`INSERT INTO observations(id,monitor_id,monitor_revision,outcome,reason_code,measurements,observed_at,duration_ms) VALUES(?,?,1,'success','reachable',?,?,1)`, last, id, metadata, at); err != nil {
			tx.Rollback()
			t.Fatal(err)
		}
	}
	if _, err := tx.Exec(`UPDATE monitor_states SET current_state='operational',last_observation_id=?,updated_at=? WHERE monitor_id=?`, last, start.Add(1000*time.Minute).UnixMilli(), id); err != nil {
		t.Fatal(err)
	}
	if err := tx.Commit(); err != nil {
		t.Fatal(err)
	}
	admin := protocol.Viewer{Subject: "admin", Role: "admin"}
	if err := s.SaveMaintenance(admin, MaintenanceInput{ComponentID: c.ID, StartsAt: start.Format(time.RFC3339), EndsAt: start.Add(time.Minute).Format(time.RFC3339), Summary: "Corrected window"}); err != nil {
		t.Fatal(err)
	}
	result, err := s.History(admin, c.ID, start, start.Add(1001*time.Minute))
	if err != nil || len(result) != 1 || result[0].OperationalMS < 900*60000 || result[0].ExcludedMS != 60000 {
		t.Fatalf("bounded multi-bucket evidence=%+v err=%v", result, err)
	}
}
