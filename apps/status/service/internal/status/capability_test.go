package status

import (
	"encoding/json"
	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
	"strings"
	"testing"
	"time"
)

func TestUnsupportedBillingIsExplicitAndCannotRecoverIncident(t *testing.T) {
	s := testStore(t)
	c := monitoredComponent(t, s)
	at := time.Now()
	for i := 0; i < 3; i++ {
		at = at.Add(2 * time.Minute)
		m, ok, err := s.ClaimDue(at)
		if err != nil || !ok {
			t.Fatal("claim failed")
		}
		if err := s.Record(m, Result{Outcome: "failure", ReasonCode: "network_unavailable"}, at); err != nil {
			t.Fatal(err)
		}
	}
	unsupported := qwenResult([]byte(`{"Success":false,"Code":"NotApplicable"}`), ProbeConfig{Currency: "CNY"})
	if unsupported.Outcome != "unsupported" || unsupported.ReasonCode != "billing_unsupported" {
		t.Fatalf("capability=%+v", unsupported)
	}
	at = at.Add(2 * time.Minute)
	m, ok, err := s.ClaimDue(at)
	if err != nil || !ok {
		t.Fatal("claim failed")
	}
	if err := s.Record(m, unsupported, at); err != nil {
		t.Fatal(err)
	}
	view, err := s.Components(protocol.Viewer{Subject: "admin", Role: "admin"}, false, at)
	if err != nil || len(view) != 1 || len(view[0].Monitors) != 1 {
		t.Fatalf("view=%+v err=%v", view, err)
	}
	observed := view[0].Monitors[0]
	if observed.Outcome != "unsupported" || observed.State != "unknown" || observed.ReasonCode != "billing_unsupported" {
		t.Fatalf("unsupported projection=%+v", observed)
	}
	raw, _ := json.Marshal(observed)
	if strings.Contains(string(raw), "balances") || strings.Contains(string(raw), "_status") {
		t.Fatalf("unsupported result has balance or private evidence: %s", raw)
	}
	var active int
	s.db.QueryRow(`SELECT COUNT(*) FROM incidents WHERE component_id=? AND resolved_at=0`, c.ID).Scan(&active)
	if active != 1 {
		t.Fatal("unsupported observation closed outage")
	}
}
