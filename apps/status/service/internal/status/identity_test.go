package status

import (
	"errors"
	"strings"
	"testing"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

func TestAuthorityMapsOnlyPlatformShapedViewers(t *testing.T) {
	valid := fixtureViewer("user", "reader", "team", "org")
	got, ok := authorityOf(valid)
	if !ok || got.admin || got.subject != valid.Subject {
		t.Fatalf("valid viewer = %+v %v", got, ok)
	}
	want := []string{"user:" + valid.Subject, "ou:" + valid.OUs[0], "ou:" + valid.OUs[1]}
	if strings.Join(got.principals, ",") != strings.Join(want, ",") {
		t.Fatalf("principals = %v want %v", got.principals, want)
	}
	if admin, ok := authorityOf(fixtureAdmin()); !ok || !admin.admin {
		t.Fatal("platform administrator role was not mapped")
	}
	manyOUs := make([]string, 65)
	for i := range manyOUs {
		manyOUs[i] = fixtureOpaque("ou", string(rune('a'+i%26))+strings.Repeat("x", i))
	}
	for name, viewer := range map[string]protocol.Viewer{
		"empty":            {},
		"readable subject": {Subject: "admin", Role: "admin"},
		"uppercase":        {Subject: strings.ToUpper(valid.Subject), Role: "user"},
		"short":            {Subject: valid.Subject[:63], Role: "user"},
		"no role":          {Subject: valid.Subject},
		"readable ou":      {Subject: valid.Subject, Role: "user", OUs: []string{"team"}},
		"duplicate ou":     {Subject: valid.Subject, Role: "user", OUs: []string{valid.OUs[0], valid.OUs[0]}},
		"too many ous":     {Subject: valid.Subject, Role: "user", OUs: manyOUs},
		"separator":        {Subject: valid.Subject, Role: "user", OUs: []string{valid.OUs[0] + ",x"}},
	} {
		if _, ok := authorityOf(viewer); ok {
			t.Errorf("%s: malformed viewer accepted", name)
		}
	}
}

func TestAdministratorRequiresPlatformShapedSubject(t *testing.T) {
	if isAdmin(protocol.Viewer{Subject: "admin", Role: "admin"}) {
		t.Fatal("readable subject treated as administrator")
	}
	if isAdmin(fixtureViewer("user", "admin")) {
		t.Fatal("non-admin role treated as administrator")
	}
	if !isAdmin(fixtureAdmin()) {
		t.Fatal("platform administrator rejected")
	}
}

func TestReadGrantsFollowOpaqueUserAndOUPrincipals(t *testing.T) {
	s := testStore(t)
	reader := fixtureViewer("user", "reader", "team")
	byUser, err := s.SaveComponent(fixtureAdmin(), ComponentInput{Label: "By user", Enabled: true, Grants: []Grant{{Principal: "user:" + reader.Subject, Permission: "read"}}})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.SaveComponent(fixtureAdmin(), ComponentInput{Label: "By OU", Enabled: true, Grants: []Grant{{Principal: fixtureOU("team"), Permission: "read"}}}); err != nil {
		t.Fatal(err)
	}
	if _, err := s.SaveComponent(fixtureAdmin(), ComponentInput{Label: "Other", Enabled: true, Grants: []Grant{{Principal: fixtureOU("elsewhere"), Permission: "read"}}}); err != nil {
		t.Fatal(err)
	}
	views, err := s.Components(reader, false, time.Now())
	if err != nil || len(views) != 2 {
		t.Fatalf("grant views = %d %v", len(views), err)
	}
	// A readable name never matches an opaque principal, so a copied legacy
	// grant such as ou:team stays inert until an administrator re-enters it.
	legacy := fixtureViewer("user", "reader")
	legacy.OUs = []string{"team"}
	if views, err := s.Components(legacy, false, time.Now()); err != nil || len(views) != 0 {
		t.Fatalf("non-platform viewer saw %d components (%v)", len(views), err)
	}
	if byUser.ID == "" {
		t.Fatal("missing component")
	}
}

func TestGrantPrincipalsMustBeOpaqueUserOrOUIdentifiers(t *testing.T) {
	s := testStore(t)
	admin := fixtureAdmin()
	hex64 := fixtureOpaque("account", "reader")
	for name, principal := range map[string]string{
		"readable name":  "user:alice",
		"short":          "ou:" + hex64[:63],
		"long":           "user:" + hex64 + "0",
		"uppercase":      "user:" + strings.ToUpper(hex64),
		"non hex":        "ou:" + strings.Repeat("g", 64),
		"unknown prefix": "group:" + hex64,
		"bare prefix":    "user:",
		"newline":        "user:" + hex64 + "\n",
		"no prefix":      hex64,
	} {
		_, err := s.SaveComponent(admin, ComponentInput{Label: "Grant " + name, Enabled: true, Grants: []Grant{{Principal: principal, Permission: "read"}}})
		if !errors.Is(err, ErrInvalid) {
			t.Errorf("%s accepted: %v", name, err)
		}
	}
	for _, principal := range []string{"user:" + hex64, "ou:" + hex64} {
		if _, err := s.SaveComponent(admin, ComponentInput{Label: "Valid " + principal[:3], Enabled: true, Grants: []Grant{{Principal: principal, Permission: "read"}}}); err != nil {
			t.Errorf("%s refused: %v", principal[:3], err)
		}
	}
}
