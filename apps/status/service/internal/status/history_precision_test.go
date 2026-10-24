package status

import (
	"encoding/json"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

func seedHistoryMonitor(t *testing.T, s *Store, created time.Time) (ComponentInput, string) {
	t.Helper()
	c := monitoredComponent(t, s)
	id := c.Monitors[0].ID
	s.db.Exec(`UPDATE monitors SET created_at=?,updated_at=?,next_at=? WHERE id=?`, created.UnixMilli(), created.UnixMilli(), created.UnixMilli(), id)
	s.db.Exec(`UPDATE monitor_states SET updated_at=? WHERE monitor_id=?`, created.UnixMilli(), id)
	return c, id
}
func historySample(t *testing.T, s *Store, id string, at time.Time) {
	t.Helper()
	m, ok, err := s.ClaimDue(at)
	if err != nil || !ok || m.ID != id {
		t.Fatalf("claim=%v %v", ok, err)
	}
	if err := s.Record(m, Result{Outcome: "success", ReasonCode: "reachable"}, at); err != nil {
		t.Fatal(err)
	}
}
func TestHistoryClipsPartialHoursAndCountsUnobservedTail(t *testing.T) {
	s := testStore(t)
	start := time.Now().UTC().Truncate(time.Hour).Add(-2 * time.Hour).Add(10 * time.Minute)
	c, id := seedHistoryMonitor(t, s, start)
	historySample(t, s, id, start.Add(time.Minute))
	historySample(t, s, id, start.Add(3*time.Minute))
	from, to := start.Add(2*time.Minute), start.Add(10*time.Minute)
	out, err := s.History(protocol.Viewer{Subject: "admin", Role: "admin"}, c.ID, from, to)
	if err != nil || len(out) != 1 {
		t.Fatalf("history=%+v err=%v", out, err)
	}
	if out[0].OperationalMS != 180000 || out[0].UnknownMS != 300000 || out[0].EligibleMS != 180000 {
		t.Fatalf("partial/tail=%+v", out[0])
	}
}
func TestHistoryHasNoDataBeforeMonitorCreation(t *testing.T) {
	s := testStore(t)
	start := time.Now().UTC().Truncate(time.Hour).Add(-2 * time.Hour)
	c, _ := seedHistoryMonitor(t, s, start)
	out, err := s.History(protocol.Viewer{Subject: "admin", Role: "admin"}, c.ID, start.Add(-time.Hour), start.Add(10*time.Minute))
	if err != nil || len(out) != 1 || out[0].UnknownMS != 600000 || out[0].OperationalMS != 0 {
		t.Fatalf("invented history=%+v err=%v", out, err)
	}
}
func TestHistoryExcludesPausedPeriodAndDoesNotCountOverlappingMaintenanceTwice(t *testing.T) {
	s := testStore(t)
	start := time.Now().UTC().Truncate(time.Hour).Add(-2 * time.Hour)
	c, id := seedHistoryMonitor(t, s, start)
	historySample(t, s, id, start.Add(time.Minute))
	historySample(t, s, id, start.Add(3*time.Minute))
	for _, event := range []struct {
		action string
		at     time.Time
	}{{"probes.pause", start.Add(4 * time.Minute)}, {"probes.resume", start.Add(8 * time.Minute)}} {
		_, err := s.db.Exec(`INSERT INTO audit_events(id,actor,action,target_id,safe_detail,created_at) VALUES(?,?,?,?,?,?)`, newID(), "admin", event.action, "service", "{}", event.at.UnixMilli())
		if err != nil {
			t.Fatal(err)
		}
	}
	for i, window := range [][2]int{{5, 7}, {6, 9}} {
		_, err := s.db.Exec(`INSERT INTO maintenance_windows(id,component_id,starts_at,ends_at,safe_summary,created_by,created_at) VALUES(?,?,?,?,?,?,?)`, string(rune('a'+i)), c.ID, start.Add(time.Duration(window[0])*time.Minute).UnixMilli(), start.Add(time.Duration(window[1])*time.Minute).UnixMilli(), "planned", "admin", start.UnixMilli())
		if err != nil {
			t.Fatal(err)
		}
	}
	out, err := s.History(protocol.Viewer{Subject: "admin", Role: "admin"}, c.ID, start, start.Add(10*time.Minute))
	if err != nil || len(out) != 1 || out[0].ExcludedMS != 300000 || out[0].OperationalMS != 60000 || out[0].UnknownMS != 240000 {
		raw, _ := json.Marshal(out)
		t.Fatalf("pause/maintenance=%s err=%v", raw, err)
	}
}

func TestHistoryCountsFullHoursOfPauseAndResumesWithFreshEvidence(t *testing.T) {
	s := testStore(t)
	start := time.Now().UTC().Truncate(time.Hour).Add(-6 * time.Hour)
	c, id := seedHistoryMonitor(t, s, start)
	historySample(t, s, id, start.Add(time.Minute))
	historySample(t, s, id, start.Add(3*time.Minute))
	s.db.Exec(`INSERT INTO audit_events VALUES(?,?,'probes.pause','service','{}',?)`, newID(), "admin", start.Add(30*time.Minute).UnixMilli())
	s.db.Exec(`INSERT INTO audit_events VALUES(?,?,'probes.resume','service','{}',?)`, newID(), "admin", start.Add(4*time.Hour+30*time.Minute).UnixMilli())
	historySample(t, s, id, start.Add(4*time.Hour+31*time.Minute))
	historySample(t, s, id, start.Add(4*time.Hour+33*time.Minute))
	out, err := s.History(protocol.Viewer{Subject: "admin", Role: "admin"}, c.ID, start, start.Add(5*time.Hour))
	if err != nil || len(out) != 1 || out[0].ExcludedMS != 4*3600000 || out[0].OperationalMS != 6*60000 {
		t.Fatalf("full pause=%+v err=%v", out, err)
	}
}

func TestPublishedHourlyHistoryHasItsOwnVisibilityGate(t *testing.T) {
	s := testStore(t)
	start := time.Now().UTC().Truncate(time.Hour).Add(-2 * time.Hour)
	c, id := seedHistoryMonitor(t, s, start)
	historySample(t, s, id, start.Add(time.Minute))
	historySample(t, s, id, start.Add(3*time.Minute))
	if _, err := s.PublicHistory(c.ID, start, start.Add(10*time.Minute)); err != ErrNotFound {
		t.Fatal("history published before explicit enablement")
	}
	s.db.Exec(`INSERT INTO settings VALUES('public_enabled','1')`)
	if _, err := s.PublicHistory(c.ID, start, start.Add(10*time.Minute)); err != ErrNotFound {
		t.Fatal("private component history published")
	}
	s.db.Exec(`UPDATE components SET public_enabled=1,public_label='Public storage' WHERE id=?`, c.ID)
	out, err := s.PublicHistory(c.ID, start, start.Add(10*time.Minute))
	if err != nil || len(out) != 1 || out[0].State != "unknown" {
		t.Fatalf("public history=%+v err=%v", out, err)
	}
	raw, _ := json.Marshal(out)
	for _, secret := range []string{"monitor_id", "balances", "health.example", "credential", "Internal"} {
		if strings.Contains(string(raw), secret) {
			t.Fatal("public history exposed private metadata")
		}
	}
}

func TestPauseResumeClosesEvidenceOnceAndRetentionKeepsPauseAnchor(t *testing.T) {
	s := testStore(t)
	start := time.Now().UTC().Truncate(time.Hour).Add(-2 * time.Hour)
	c, id := seedHistoryMonitor(t, s, start)
	historySample(t, s, id, start.Add(time.Minute))
	historySample(t, s, id, start.Add(3*time.Minute))
	admin := protocol.Viewer{Subject: "admin", Role: "admin"}
	if err := s.SaveSettings(admin, ServiceSettings{ProbesPaused: true}); err != nil {
		t.Fatal(err)
	}
	var count int
	s.db.QueryRow(`SELECT COUNT(*) FROM audit_events WHERE action='probes.pause'`).Scan(&count)
	if count != 1 {
		t.Fatal("pause has no durable time boundary")
	}
	fingerprint, err := s.QueueFingerprint()
	if err != nil {
		t.Fatal(err)
	}
	if err := s.Resume(admin, fingerprint, true, false); err != nil {
		t.Fatal(err)
	}
	out, err := s.History(admin, c.ID, start, time.Now())
	if err != nil || len(out) != 1 || out[0].OperationalMS != 180000 {
		t.Fatalf("closed evidence counted twice or lost: %+v %v", out, err)
	}
	old := time.Now().Add(-120 * 24 * time.Hour).UnixMilli()
	_, err = s.db.Exec(`INSERT INTO audit_events VALUES('old-pause','admin','probes.pause','long-paused-service','{}',?)`, old)
	if err != nil {
		t.Fatal(err)
	}
	if err := s.Cleanup(time.Now()); err != nil {
		t.Fatal(err)
	}
	s.db.QueryRow(`SELECT COUNT(*) FROM audit_events WHERE id='old-pause'`).Scan(&count)
	if count != 1 {
		t.Fatal("retention removed the open pause anchor")
	}
}

func TestHistoryPauseOrderUsesCommitOrderWithinSameMillisecond(t *testing.T) {
	s := testStore(t)
	start := time.Now().UTC().Truncate(time.Hour).Add(-2 * time.Hour)
	c, id := seedHistoryMonitor(t, s, start)
	historySample(t, s, id, start.Add(time.Minute))
	historySample(t, s, id, start.Add(3*time.Minute))
	at := start.Add(4 * time.Minute).UnixMilli()
	s.db.Exec(`INSERT INTO audit_events VALUES('z-pause','admin','probes.pause','service','{}',?)`, at)
	s.db.Exec(`INSERT INTO audit_events VALUES('a-resume','admin','probes.resume','service','{}',?)`, at)
	out, err := s.History(protocol.Viewer{Subject: "admin", Role: "admin"}, c.ID, start, start.Add(10*time.Minute))
	// Resume invalidates prior green evidence, but a zero-length pause excludes no time.
	if err != nil || len(out) != 1 || out[0].ExcludedMS != 0 || out[0].OperationalMS != 60000 {
		t.Fatalf("same-ms order=%+v err=%v", out, err)
	}
}
func TestRestoreDoesNotRewriteEarlierHistory(t *testing.T) {
	s := testStore(t)
	start := time.Now().UTC().Truncate(time.Hour).Add(-2 * time.Hour)
	c, id := seedHistoryMonitor(t, s, start)
	historySample(t, s, id, start.Add(time.Minute))
	historySample(t, s, id, start.Add(3*time.Minute))
	admin := protocol.Viewer{Subject: "admin", Role: "admin"}
	before, err := s.History(admin, c.ID, start, start.Add(10*time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	file := filepath.Join(t.TempDir(), "snapshot.db")
	if err := s.Backup(file); err != nil {
		t.Fatal(err)
	}
	if err := s.Restore(file); err != nil {
		t.Fatal(err)
	}
	after, err := s.History(admin, c.ID, start, start.Add(10*time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(before, after) {
		t.Fatalf("restore rewrote history: before=%+v after=%+v", before, after)
	}
}

func TestFutureMaintenancePreservesExistingEvidence(t *testing.T) {
	s := testStore(t)
	start := time.Now().UTC().Truncate(time.Hour).Add(-2 * time.Hour)
	c, id := seedHistoryMonitor(t, s, start)
	historySample(t, s, id, start.Add(time.Minute))
	historySample(t, s, id, start.Add(3*time.Minute))
	admin := protocol.Viewer{Subject: "admin", Role: "admin"}
	before, err := s.History(admin, c.ID, start, start.Add(10*time.Minute))
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now()
	if err := s.SaveMaintenance(admin, MaintenanceInput{ComponentID: c.ID, StartsAt: now.Add(time.Hour).UTC().Format(time.RFC3339), EndsAt: now.Add(2 * time.Hour).UTC().Format(time.RFC3339), Summary: "Scheduled"}); err != nil {
		t.Fatal(err)
	}
	after, err := s.History(admin, c.ID, start, start.Add(10*time.Minute))
	if err != nil || !reflect.DeepEqual(before, after) {
		t.Fatalf("future maintenance rewrote history: before=%+v after=%+v err=%v", before, after, err)
	}
	var state string
	if err := s.db.QueryRow(`SELECT current_state FROM monitor_states WHERE monitor_id=?`, id).Scan(&state); err != nil || state != "operational" {
		t.Fatalf("future maintenance reset current state=%s err=%v", state, err)
	}
}
