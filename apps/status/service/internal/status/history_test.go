package status

import (
	"encoding/json"
	"strings"
	"testing"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

func TestHistoryFiltersBeforeCountsAndRejectsHiddenDetails(t *testing.T) {
	s := testStore(t)
	c := monitoredComponent(t, s)
	now := time.Now().Add(time.Minute)
	for range 3 {
		m, ok, _ := s.ClaimDue(now)
		if !ok {
			t.Fatal("claim failed")
		}
		if err := s.Record(m, Result{Outcome: "failure", ReasonCode: "network_unavailable"}, now); err != nil {
			t.Fatal(err)
		}
		now = now.Add(2 * time.Minute)
	}
	s.db.Exec(`INSERT INTO component_grants VALUES(?,?,'read')`, c.ID, "ou:one")
	one := protocol.Viewer{Subject: "one", Role: "user", OUs: []string{"one"}}
	two := protocol.Viewer{Subject: "two", Role: "user", OUs: []string{"two"}}
	visible, err := s.Incidents(one, false, 0, 50)
	if err != nil || len(visible.Items) != 1 || visible.Total != 1 {
		t.Fatalf("visible=%+v err=%v", visible, err)
	}
	hidden, err := s.Incidents(two, false, 0, 50)
	if err != nil || len(hidden.Items) != 0 || hidden.Total != 0 {
		t.Fatal("hidden count leaked")
	}
	if _, err := s.Incident(two, visible.Items[0].ID, false); err != ErrNotFound {
		t.Fatal("hidden detail disclosed")
	}
	if _, err := s.History(two, c.ID, now.Add(-time.Hour), now); err != ErrNotFound {
		t.Fatal("hidden aggregate disclosed")
	}
	public, err := s.Incidents(protocol.Viewer{}, true, 0, 50)
	if err != nil || len(public.Items) != 0 {
		t.Fatal("unpublished narrative leaked")
	}
}
func TestMaintenanceAndPublicNarrativeAreExplicit(t *testing.T) {
	s := testStore(t)
	c := monitoredComponent(t, s)
	admin := protocol.Viewer{Subject: "admin", Role: "admin"}
	now := time.Now()
	if err := s.SaveMaintenance(admin, MaintenanceInput{ComponentID: c.ID, StartsAt: now.Add(-time.Minute).UTC().Format(time.RFC3339), EndsAt: now.Add(time.Hour).UTC().Format(time.RFC3339), Summary: "Planned work"}); err != nil {
		t.Fatal(err)
	}
	components, err := s.Components(admin, false, now)
	if err != nil || components[0].State != "maintenance" {
		t.Fatal("maintenance invisible")
	}
	if err := s.SaveMaintenance(admin, MaintenanceInput{ComponentID: c.ID, StartsAt: now.Format(time.RFC3339), EndsAt: now.Add(-time.Hour).Format(time.RFC3339)}); err != ErrInvalid {
		t.Fatal("invalid maintenance accepted")
	}
	s.db.Exec(`INSERT INTO incidents(id,component_id,state,safe_summary,private_detail,opened_at,revision) VALUES('incident',?,'outage','Private summary','secret-host',?,1)`, c.ID, now.UnixMilli())
	if err := s.PublishIncident(admin, "incident", 1, "Service is being restored", true); err != nil {
		t.Fatal(err)
	}
	s.db.Exec(`UPDATE components SET public_enabled=1,public_label='Public service' WHERE id=?`, c.ID)
	s.db.Exec(`INSERT INTO settings VALUES('public_enabled','1')`)
	public, err := s.Incident(protocol.Viewer{}, "incident", true)
	raw, _ := json.Marshal(public)
	if err != nil || strings.Contains(string(raw), "secret-host") || strings.Contains(string(raw), "Private summary") || !strings.Contains(string(raw), "Service is being restored") {
		t.Fatalf("public=%s err=%v", raw, err)
	}
}
