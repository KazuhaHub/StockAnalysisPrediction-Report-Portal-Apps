package status

import (
	"encoding/json"
	"fmt"
	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
	"strings"
	"testing"
	"time"
)

func TestComponentPagingSearchDetailAndExportShareCurrentAuthority(t *testing.T) {
	s := testStore(t)
	admin := protocol.Viewer{Subject: "admin", Role: "admin"}
	reader := protocol.Viewer{Subject: "reader", Role: "user", OUs: []string{"a"}}
	var owned, hidden ComponentInput
	for i := 0; i < 64; i++ {
		ou := "a"
		if i >= 61 {
			ou = "b"
		}
		c, err := s.SaveComponent(admin, ComponentInput{Label: fmt.Sprintf("Component %03d", i), Enabled: true, Grants: []Grant{{Principal: "ou:" + ou, Permission: "read"}}})
		if err != nil {
			t.Fatal(err)
		}
		if i == 60 {
			owned = c
		}
		if i == 63 {
			hidden = c
		}
	}
	page, err := s.ComponentPage(reader, time.Now(), 50, 50, "")
	if err != nil || page.Total != 61 || len(page.Items) != 11 {
		t.Fatalf("page=%+v err=%v", page, err)
	}
	search, err := s.ComponentPage(reader, time.Now(), 0, 50, "Component 063")
	if err != nil || search.Total != 0 || len(search.Items) != 0 {
		t.Fatal("search revealed hidden component")
	}
	if _, err := s.Component(reader, hidden.ID, time.Now()); err != ErrNotFound {
		t.Fatal("hidden detail disclosed")
	}
	if _, err := s.Component(reader, owned.ID, time.Now()); err != nil {
		t.Fatal(err)
	}
	now := time.Now()
	export, err := s.ExportComponent(reader, owned.ID, now.Add(-time.Hour), now)
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(export)
	if len(raw) > 512*1024 || strings.Contains(string(raw), hidden.ID) || strings.Contains(string(raw), "credential") {
		t.Fatal("unbounded or private export")
	}
	reader.OUs = []string{"b"}
	if _, err := s.ExportComponent(reader, owned.ID, now.Add(-time.Hour), now); err != ErrNotFound {
		t.Fatal("revoked OU exported old detail")
	}
	for _, limit := range []int{0, 101} {
		if _, err := s.ComponentPage(admin, now, 0, limit, ""); err != ErrInvalid {
			t.Fatal("unbounded page limit")
		}
	}
}

func TestComponentExportRequiresSeparateCurrentFinanceGrant(t *testing.T) {
	s := testStore(t)
	admin := protocol.Viewer{Subject: "admin", Role: "admin"}
	reader := protocol.Viewer{Subject: "reader", Role: "user", OUs: []string{"a"}}
	c := monitoredComponent(t, s)
	c.Grants = []Grant{{Principal: "ou:a", Permission: "read"}}
	var err error
	c, err = s.SaveComponent(admin, c)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now().Add(time.Second)
	monitor, ok, err := s.ClaimDue(now)
	if err != nil || !ok {
		t.Fatal("claim failed")
	}
	if err := s.Record(monitor, Result{Outcome: "success", ReasonCode: "balance_read", Measurements: Measurements{Balances: []Balance{{Currency: "CNY", Total: "12345.6789"}}}}, now); err != nil {
		t.Fatal(err)
	}
	export, err := s.ExportComponent(reader, c.ID, now.Add(-time.Hour), now.Add(time.Second))
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(export)
	if strings.Contains(string(raw), "12345.6789") || strings.Contains(string(raw), "health.example") || strings.Contains(string(raw), "_status") {
		t.Fatal("read-only export leaked financial/configuration/evidence details")
	}
	if _, err := s.db.Exec(`INSERT INTO component_grants VALUES(?,'ou:a','finance')`, c.ID); err != nil {
		t.Fatal(err)
	}
	export, err = s.ExportComponent(reader, c.ID, now.Add(-time.Hour), now.Add(time.Second))
	if err != nil {
		t.Fatal(err)
	}
	raw, _ = json.Marshal(export)
	if !strings.Contains(string(raw), "12345.6789") || strings.Contains(string(raw), "_status") {
		t.Fatal("finance grant was ignored or internal evidence exposed")
	}
}

func TestPublicComponentPagesCountOnlyExplicitPublication(t *testing.T) {
	s := testStore(t)
	admin := protocol.Viewer{Subject: "admin", Role: "admin"}
	now := time.Now()
	for i := 0; i < 3; i++ {
		_, err := s.SaveComponent(admin, ComponentInput{Label: "Private label", PublicLabel: fmt.Sprintf("Public %d", i), PublicEnabled: i < 2, Enabled: true})
		if err != nil {
			t.Fatal(err)
		}
	}
	page, err := s.PublicComponentPage(now, 0, 1)
	if err != nil || page.Total != 0 || len(page.Items) != 0 {
		t.Fatal("public counts exposed before global publication")
	}
	if _, err := s.db.Exec(`INSERT INTO settings(key,value) VALUES('public_enabled','1')`); err != nil {
		t.Fatal(err)
	}
	page, err = s.PublicComponentPage(now, 1, 1)
	if err != nil || page.Total != 2 || len(page.Items) != 1 || page.Items[0].Label == "Private label" {
		t.Fatalf("public page=%+v err=%v", page, err)
	}
	if _, err := s.PublicComponentPage(now, 0, 101); err != ErrInvalid {
		t.Fatal("unbounded public page")
	}
}
