package status

import (
	"bytes"
	"net/http/httptest"
	"strings"
	"testing"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

func TestPublicWebsiteRequiresExplicitPublication(t *testing.T) {
	store := testStore(t)
	server, err := NewServer(store, protocol.Signer{Issuer: "portal", Audience: "status", AppID: "status", InstanceID: "one", KeyID: "key", Key: bytes.Repeat([]byte{2}, 32)})
	if err != nil {
		t.Fatal(err)
	}
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
