package status

import (
	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
	"testing"
	"time"
)

func TestExpiredProbeAfterRestartRecordsUnknownAndRequiresFreshConfirmation(t *testing.T) {
	s := testStore(t)
	start := time.Now().Add(-20 * time.Minute)
	_, id := seedHistoryMonitor(t, s, start)
	historySample(t, s, id, start.Add(time.Minute))
	historySample(t, s, id, start.Add(3*time.Minute))
	claimedAt := start.Add(5 * time.Minute)
	lost, ok, err := s.ClaimDue(claimedAt)
	if err != nil || !ok {
		t.Fatalf("claim=%v %v", ok, err)
	}
	if err := s.db.Close(); err != nil {
		t.Fatal(err)
	}
	if err := s.openDB(); err != nil {
		t.Fatal(err)
	}
	recoveredAt := claimedAt.Add(2 * time.Minute)
	if _, ok, err := s.ClaimDue(recoveredAt); err != nil || ok {
		t.Fatalf("expired check relaunched before evidence/retry delay: %v %v", ok, err)
	}
	var state, reason, outcome string
	if err := s.db.QueryRow(`SELECT s.current_state,o.reason_code,o.outcome FROM monitor_states s JOIN observations o ON o.id=s.last_observation_id WHERE s.monitor_id=?`, id).Scan(&state, &reason, &outcome); err != nil || state != "unknown" || reason != "observer_unavailable" || outcome != "unknown" {
		t.Fatalf("missing observer evidence state=%s reason=%s outcome=%s err=%v", state, reason, outcome, err)
	}
	if err := s.Record(lost, Result{Outcome: "success", ReasonCode: "reachable"}, recoveredAt); err != ErrConflict {
		t.Fatalf("expired result applied: %v", err)
	}
	historySample(t, s, id, recoveredAt.Add(2*time.Minute))
	s.db.QueryRow(`SELECT current_state FROM monitor_states WHERE monitor_id=?`, id).Scan(&state)
	if state != "unknown" {
		t.Fatal("first post-restart sample recovered without confirmation")
	}
	historySample(t, s, id, recoveredAt.Add(4*time.Minute))
	s.db.QueryRow(`SELECT current_state FROM monitor_states WHERE monitor_id=?`, id).Scan(&state)
	if state != "operational" {
		t.Fatal("two fresh samples did not recover")
	}
	var count int
	s.db.QueryRow(`SELECT COUNT(*) FROM observations WHERE monitor_id=? AND reason_code='observer_unavailable'`, id).Scan(&count)
	if count != 1 {
		t.Fatalf("observer evidence duplicated=%d", count)
	}
}

func TestManualProbeRequestHonorsPauseRevisionAndThrottle(t *testing.T) {
	s := testStore(t)
	c := monitoredComponent(t, s)
	admin := protocol.Viewer{Subject: "admin", Role: "admin"}
	monitor := c.Monitors[0]
	if err := s.RequestProbe(protocol.Viewer{Subject: "reader", Role: "user"}, monitor.ID, 1); err != ErrForbidden {
		t.Fatalf("reader requested probe: %v", err)
	}
	if err := s.RequestProbe(admin, monitor.ID, 999); err != ErrConflict {
		t.Fatalf("stale revision queued: %v", err)
	}
	s.db.Exec(`INSERT INTO settings(key,value) VALUES('probes_paused','1')`)
	if err := s.RequestProbe(admin, monitor.ID, 1); err != ErrConflict {
		t.Fatalf("pause bypassed: %v", err)
	}
	s.db.Exec(`UPDATE settings SET value='0' WHERE key='probes_paused'`)
	s.db.Exec(`UPDATE monitors SET next_at=? WHERE id=?`, time.Now().Add(time.Hour).UnixMilli(), monitor.ID)
	if err := s.RequestProbe(admin, monitor.ID, 1); err != nil {
		t.Fatal(err)
	}
	if err := s.RequestProbe(admin, monitor.ID, 1); err != ErrConflict {
		t.Fatalf("throttle bypassed: %v", err)
	}
	var count int
	s.db.QueryRow(`SELECT COUNT(*) FROM observations`).Scan(&count)
	if count != 0 {
		t.Fatal("request fabricated successful observation")
	}
	claimed, ok, err := s.ClaimDue(time.Now().Add(time.Second))
	if err != nil || !ok || claimed.ID != monitor.ID {
		t.Fatalf("requested probe not due=%v %v", ok, err)
	}
}
