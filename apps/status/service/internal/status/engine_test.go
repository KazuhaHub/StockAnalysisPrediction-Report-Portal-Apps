package status

import (
	"encoding/json"
	"testing"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

func monitoredComponent(t *testing.T, s *Store) ComponentInput {
	t.Helper()
	c, err := s.SaveComponent(protocol.Viewer{Subject: "admin", Role: "admin"}, ComponentInput{Label: "HTTP health", Enabled: true, Monitors: []MonitorInput{{Label: "Read health", Kind: "http", Config: json.RawMessage(`{"url":"https://health.example"}`), Enabled: true, IntervalSeconds: 60, TimeoutSeconds: 5}}})
	if err != nil {
		t.Fatal(err)
	}
	return c
}
func TestReducerOpensOnceAndUnknownDoesNotRecover(t *testing.T) {
	s := testStore(t)
	c := monitoredComponent(t, s)
	now := time.Now()
	sample := func(outcome string) {
		t.Helper()
		now = now.Add(2 * time.Minute)
		m, ok, err := s.ClaimDue(now)
		if err != nil || !ok {
			t.Fatalf("claim=%v %v", ok, err)
		}
		if err := s.Record(m, Result{Outcome: outcome, ReasonCode: "reachable"}, now); err != nil {
			t.Fatal(err)
		}
	}
	sample("failure")
	sample("failure")
	var incidents int
	s.db.QueryRow(`SELECT COUNT(*) FROM incidents`).Scan(&incidents)
	if incidents != 0 {
		t.Fatal("incident opened before confirmation")
	}
	sample("failure")
	sample("failure")
	s.db.QueryRow(`SELECT COUNT(*) FROM incidents WHERE resolved_at=0`).Scan(&incidents)
	if incidents != 1 {
		t.Fatal("duplicate or missing incident")
	}
	sample("unknown")
	sample("success")
	s.db.QueryRow(`SELECT COUNT(*) FROM incidents WHERE resolved_at=0`).Scan(&incidents)
	if incidents != 1 {
		t.Fatal("unknown or first success falsely resolved incident")
	}
	sample("success")
	s.db.QueryRow(`SELECT COUNT(*) FROM incidents WHERE resolved_at=0`).Scan(&incidents)
	if incidents != 0 {
		t.Fatal("confirmed recovery did not resolve incident")
	}
	var transitions int
	s.db.QueryRow(`SELECT COUNT(*) FROM incident_transitions`).Scan(&transitions)
	if transitions != 2 {
		t.Fatalf("transitions=%d", transitions)
	}
	_ = c
}
func TestLeaseAndRevisionFenceDiscardStaleResults(t *testing.T) {
	s := testStore(t)
	c := monitoredComponent(t, s)
	now := time.Now().Add(time.Minute)
	m, ok, err := s.ClaimDue(now)
	if err != nil || !ok {
		t.Fatal("first claim failed")
	}
	if _, ok, err := s.ClaimDue(now); err != nil || ok {
		t.Fatal("same monitor leased twice")
	}
	if _, err := s.SaveComponent(protocol.Viewer{Subject: "admin", Role: "admin"}, c); err != nil {
		t.Fatal(err)
	}
	if err := s.Record(m, Result{Outcome: "failure", ReasonCode: "network_unavailable"}, now); err != ErrConflict {
		t.Fatalf("stale result=%v", err)
	}
	var n int
	s.db.QueryRow(`SELECT COUNT(*) FROM observations`).Scan(&n)
	if n != 0 {
		t.Fatal("stale observation persisted")
	}
}

func TestUptimeNeverBackfillsAnIntervalWithItsNewState(t *testing.T) {
	s := testStore(t)
	monitoredComponent(t, s)
	now := time.Now().Add(time.Minute)
	m, ok, err := s.ClaimDue(now)
	if err != nil || !ok {
		t.Fatal("claim failed")
	}
	if err := s.Record(m, Result{Outcome: "success", ReasonCode: "reachable"}, now); err != nil {
		t.Fatal(err)
	}
	now = now.Add(2 * time.Minute)
	m, ok, err = s.ClaimDue(now)
	if err != nil || !ok {
		t.Fatal("second claim failed")
	}
	if err := s.Record(m, Result{Outcome: "success", ReasonCode: "reachable"}, now); err != nil {
		t.Fatal(err)
	}
	var healthy int64
	s.db.QueryRow(`SELECT COALESCE(SUM(operational_ms),0) FROM hourly_aggregates`).Scan(&healthy)
	if healthy != 0 {
		t.Fatalf("confirmed recovery retroactively rewrote %d ms as healthy", healthy)
	}
}
