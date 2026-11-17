package status

import (
	"net/http/httptest"
	"strings"
	"testing"
)

func TestPublicWebsiteRequiresExplicitPublication(t *testing.T) {
	store := testStore(t)
	server, _ := newTestServer(t, store)
	request := func(path string) *httptest.ResponseRecorder {
		r := httptest.NewRequest("GET", path, nil)
		w := httptest.NewRecorder()
		server.ServeHTTP(w, r)
		return w
	}
	if w := request("/"); w.Code != 404 {
		t.Fatal("public website available by default")
	}
	store.db.Exec(`INSERT INTO settings VALUES('public_enabled','1')`)
	if w := request("/"); w.Code != 200 || !strings.Contains(w.Body.String(), `src="app.js"`) {
		t.Fatalf("prefix-aware website=%d %s", w.Code, w.Body.String())
	}
	if w := request("/app.js"); w.Code != 200 || !strings.Contains(w.Body.String(), "public/v1/") {
		t.Fatal("public assets unavailable")
	}
	if w := request("/public/v1/incidents"); w.Code != 200 || strings.Contains(w.Body.String(), "private_detail") {
		t.Fatal("public incident DTO invalid")
	}
	if w := request("/readyz"); w.Code != 200 {
		t.Fatal("readiness unavailable")
	}
}
