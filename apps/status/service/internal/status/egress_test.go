package status

import (
	"context"
	"encoding/json"
	"testing"
	"time"
)

func TestWithoutEgressProbesReportUnknownAndNeverDial(t *testing.T) {
	prober := &Prober{Egress: NoEgress{}}
	for _, kind := range []string{"http", "dify", "deepseek", "qwen", "postgres"} {
		m := Monitor{ID: "m", Kind: kind, Config: ProbeConfig{URL: "https://health.example", Host: "database.example", Port: 5432}}
		result := prober.Check(context.Background(), m)
		if result.Outcome != "unknown" || result.ReasonCode != "egress_unavailable" {
			t.Errorf("%s result=%+v", kind, result)
		}
	}
}

func TestWithoutEgressNoIncidentOpensAndStateIsUnknown(t *testing.T) {
	s := testStore(t)
	c := monitoredComponent(t, s)
	prober := &Prober{Egress: NoEgress{}}
	at := time.Now()
	for i := 0; i < 5; i++ {
		at = at.Add(2 * time.Minute)
		m, ok, err := s.ClaimDue(at)
		if err != nil || !ok {
			t.Fatalf("claim=%v %v", ok, err)
		}
		if err := s.Record(m, prober.Check(context.Background(), m), at); err != nil {
			t.Fatal(err)
		}
	}
	var incidents int
	s.db.QueryRow(`SELECT COUNT(*) FROM incidents WHERE component_id=?`, c.ID).Scan(&incidents)
	if incidents != 0 {
		t.Fatalf("an unavailable network path opened %d incidents", incidents)
	}
	view, err := s.Components(fixtureAdmin(), false, at)
	if err != nil || len(view) != 1 || view[0].Monitors[0].State != "unknown" || view[0].Monitors[0].ReasonCode != "egress_unavailable" {
		raw, _ := json.Marshal(view)
		t.Fatalf("projection=%s err=%v", raw, err)
	}
}

func TestWithoutEgressNotificationsStayQueued(t *testing.T) {
	s, _ := outboxFixture(t)
	if _, err := s.db.Exec(`UPDATE notification_outbox SET next_at=0`); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 1500*time.Millisecond)
	defer cancel()
	s.PublishLoop(ctx, &Publisher{Egress: NoEgress{}})
	var pending, attempts int
	if err := s.db.QueryRow(`SELECT COUNT(*),COALESCE(SUM(attempts),0) FROM notification_outbox WHERE state='pending'`).Scan(&pending, &attempts); err != nil {
		t.Fatal(err)
	}
	if pending != 1 || attempts != 0 {
		t.Fatalf("pending=%d attempts=%d: queued notices were consumed without a send path", pending, attempts)
	}
}
