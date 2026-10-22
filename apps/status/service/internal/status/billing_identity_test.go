package status

import (
	"encoding/json"
	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
	"strings"
	"testing"
	"time"
)

func TestSharedBillingAccountCannotBecomeIndependentPools(t *testing.T) {
	s := testStore(t)
	admin := protocol.Viewer{Subject: "admin", Role: "admin"}
	makeCredential := func(key string) string {
		c, err := s.SaveCredential(admin, CredentialInput{Kind: "deepseek", Label: "Billing key", Secret: json.RawMessage(`{"api_key":"` + key + `"}`)})
		if err != nil {
			t.Fatal(err)
		}
		return c.ID
	}
	a, b := makeCredential("fixture-a"), makeCredential("fixture-b")
	create := func(credential, account, currency string) (ComponentInput, error) {
		config, _ := json.Marshal(map[string]any{"account_ref": account, "currency": currency})
		return s.SaveComponent(admin, ComponentInput{Label: "Billing account", Enabled: true, Monitors: []MonitorInput{{Label: "Balance", Kind: "deepseek", CredentialID: credential, Config: config, Enabled: true, IntervalSeconds: 300, TimeoutSeconds: 5}}})
	}
	if _, err := create(a, "", "CNY"); err != ErrInvalid {
		t.Fatalf("account identity omitted=%v", err)
	}
	first, err := create(a, "shared-research", "CNY")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := create(b, "shared-research", "CNY"); err != ErrConflict {
		t.Fatalf("two keys became independent pools=%v", err)
	}
	if _, err := create(b, "shared-research", "USD"); err != ErrConflict {
		t.Fatalf("currency split same account into another component=%v", err)
	}
	if _, err := create(b, "independent-account", "CNY"); err != nil {
		t.Fatal(err)
	}
	if _, err := create(a, "another-alias", "CNY"); err != ErrConflict {
		t.Fatalf("credential split into multiple aliases=%v", err)
	}
	// Multiple currencies may share one component, with one sample per currency.
	first.Monitors = append(first.Monitors, MonitorInput{Label: "USD balance", Kind: "deepseek", CredentialID: a, Config: json.RawMessage(`{"account_ref":"shared-research","currency":"USD"}`), Enabled: true, IntervalSeconds: 300, TimeoutSeconds: 5})
	if _, err := s.SaveComponent(admin, first); err != nil {
		t.Fatalf("same-account currency projection refused=%v", err)
	}
	views, err := s.Components(admin, false, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(views)
	if strings.Contains(string(raw), "shared-research") || strings.Contains(string(raw), "fixture-a") {
		t.Fatal("billing identity or secret escaped administrator configuration")
	}
}
