package status

import (
	"bytes"
	"encoding/json"
	"errors"
	"testing"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

func TestComponentAccessAndPublicProjection(t *testing.T) {
	s := testStore(t)
	admin := protocol.Viewer{Subject: "admin", Role: "admin"}
	reader := protocol.Viewer{Subject: "reader", Role: "user", OUs: []string{"team"}}
	c, err := s.SaveComponent(admin, ComponentInput{Label: "Internal database target", PublicLabel: "Report storage", PublicEnabled: true, Enabled: true, Grants: []Grant{{Principal: "ou:team", Permission: "read"}}})
	if err != nil {
		t.Fatal(err)
	}
	components, err := s.Components(reader, false, time.Now())
	if err != nil || len(components) != 1 {
		t.Fatalf("OU access: %v %v", components, err)
	}
	foreign := reader
	foreign.OUs = []string{"foreign"}
	components, err = s.Components(foreign, false, time.Now())
	if err != nil || len(components) != 0 {
		t.Fatal("foreign OU read component")
	}
	public, err := s.Components(protocol.Viewer{}, true, time.Now())
	if err != nil || len(public) != 0 {
		t.Fatal("public enabled without global review")
	}
	s.db.Exec(`INSERT INTO settings(key,value) VALUES('public_enabled','1')`)
	public, err = s.Components(protocol.Viewer{}, true, time.Now())
	raw, _ := json.Marshal(public)
	if err != nil || len(public) != 1 || bytes.Contains(raw, []byte("Internal database")) || bytes.Contains(raw, []byte("ou:team")) {
		t.Fatalf("public projection=%s err=%v", raw, err)
	}
	if c.ID == "" {
		t.Fatal("missing opaque identity")
	}
}
func TestComponentRevisionAndCredentialDeletion(t *testing.T) {
	s := testStore(t)
	admin := protocol.Viewer{Subject: "admin", Role: "admin"}
	credential, err := s.SaveCredential(admin, CredentialInput{Kind: "deepseek", Label: "Account A", Secret: json.RawMessage(`{"api_key":"private-key"}`)})
	if err != nil {
		t.Fatal(err)
	}
	in := ComponentInput{Label: "Account A", Enabled: true, Monitors: []MonitorInput{{Label: "Balance", Kind: "deepseek", CredentialID: credential.ID, Config: json.RawMessage(`{}`), Enabled: true, IntervalSeconds: 300, TimeoutSeconds: 5}}}
	c, err := s.SaveComponent(admin, in)
	if err != nil {
		t.Fatal(err)
	}
	in.ID = c.ID
	in.Revision = 0
	if _, err := s.SaveComponent(admin, in); !errors.Is(err, ErrConflict) {
		t.Fatalf("stale write=%v", err)
	}
	if err := s.DeleteCredential(admin, credential.ID, credential.Revision); err == nil {
		t.Fatal("referenced credential deleted")
	}
	reader := protocol.Viewer{Subject: "reader", Role: "user"}
	if _, err := s.SaveComponent(reader, ComponentInput{Label: "Cannot create"}); !errors.Is(err, ErrForbidden) {
		t.Fatal("reader changed configuration")
	}
}
func TestFinanceRequiresSeparateGrant(t *testing.T) {
	s := testStore(t)
	admin := protocol.Viewer{Subject: "admin", Role: "admin"}
	c, err := s.SaveComponent(admin, ComponentInput{Label: "Provider", Enabled: true, Grants: []Grant{{Principal: "ou:team", Permission: "read"}}})
	if err != nil {
		t.Fatal(err)
	}
	reader := protocol.Viewer{Subject: "reader", Role: "user", OUs: []string{"team"}}
	if s.canRead(reader, c.ID, "finance") {
		t.Fatal("read implied finance")
	}
	if _, err := s.db.Exec(`INSERT INTO component_grants(component_id,principal,permission) VALUES(?,?,'finance')`, c.ID, "ou:team"); err != nil {
		t.Fatal(err)
	}
	if !s.canRead(reader, c.ID, "finance") {
		t.Fatal("explicit finance grant denied")
	}
}

func TestSnapshotDoesNotInventAnObservationAndExposesPause(t *testing.T) {
	s := testStore(t)
	monitoredComponent(t, s)
	admin := protocol.Viewer{Subject: "admin", Role: "admin"}
	components, err := s.Components(admin, false, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if components[0].Monitors[0].ObservedAt != "" {
		t.Fatal("configuration timestamp presented as observation")
	}
	s.db.Exec(`INSERT INTO settings VALUES('probes_paused','1')`)
	components, err = s.Components(admin, false, time.Now())
	if err != nil || components[0].State != "paused" {
		t.Fatal("pause not visible")
	}
}
