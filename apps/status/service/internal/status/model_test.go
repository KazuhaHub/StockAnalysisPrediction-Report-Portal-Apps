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
	in := ComponentInput{Label: "Account A", Enabled: true, Monitors: []MonitorInput{{Label: "Balance", Kind: "deepseek", CredentialID: credential.ID, Config: json.RawMessage(`{"account_ref":"account-a"}`), Enabled: true, IntervalSeconds: 300, TimeoutSeconds: 5}}}
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

func TestLastSuccessExpiresInPrivateAndPublicSnapshotsWithoutRewritingItsTime(t *testing.T) {
	s := testStore(t)
	admin := protocol.Viewer{Subject: "admin", Role: "admin"}
	component := monitoredComponent(t, s)
	component.PublicEnabled = true
	component.PublicLabel = "Approved health"
	component, err := s.SaveComponent(admin, component)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.db.Exec(`INSERT INTO settings(key,value) VALUES('public_enabled','1')`); err != nil {
		t.Fatal(err)
	}
	first := time.Now().UTC().Truncate(time.Millisecond).Add(time.Second)
	last := first.Add(2 * time.Minute)
	for _, at := range []time.Time{first, last} {
		monitor, ok, err := s.ClaimDue(at)
		if err != nil || !ok {
			t.Fatalf("claim=%v %v", ok, err)
		}
		if err := s.Record(monitor, Result{Outcome: "success", ReasonCode: "reachable"}, at); err != nil {
			t.Fatal(err)
		}
	}
	for _, test := range []struct {
		name  string
		now   time.Time
		stale bool
	}{
		{"fresh", last.Add(time.Minute), false},
		{"exact-ttl", last.Add(3 * time.Minute), false},
		{"expired", last.Add(3*time.Minute + time.Millisecond), true},
	} {
		t.Run(test.name, func(t *testing.T) {
			private, err := s.Component(admin, component.ID, test.now)
			if err != nil {
				t.Fatal(err)
			}
			expected := "operational"
			if test.stale {
				expected = "unknown"
			}
			if private.State != expected || private.Stale != test.stale || len(private.Monitors) != 1 || private.Monitors[0].Stale != test.stale {
				t.Fatalf("private expiry=%+v", private)
			}
			if private.ObservedAt != last.Format(time.RFC3339Nano) || private.Monitors[0].LastSuccessAt != last.Format(time.RFC3339Nano) {
				t.Fatal("reading stale evidence invented a new success time")
			}
			public, err := s.PublicComponentPage(test.now, 0, 50)
			if err != nil || len(public.Items) != 1 {
				t.Fatalf("public=%+v err=%v", public, err)
			}
			if public.Items[0].State != expected || public.Items[0].Stale != test.stale || public.Items[0].Label != "Approved health" || len(public.Items[0].Monitors) != 0 {
				t.Fatalf("public expiry=%+v", public.Items[0])
			}
		})
	}
}
