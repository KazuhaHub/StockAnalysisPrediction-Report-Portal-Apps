package status

import (
	"bytes"
	"encoding/json"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

func TestManagementEndpointsKeepSettingsAndSecretsSeparate(t *testing.T) {
	store := testStore(t)
	signer := protocol.Signer{Issuer: "portal", Audience: "status", AppID: "status", InstanceID: "one", KeyID: "key", Key: bytes.Repeat([]byte{4}, 32)}
	server, err := NewServer(store, signer)
	if err != nil {
		t.Fatal(err)
	}
	signer.BootID = server.signer.BootID
	call := func(method, path, body string) *httptest.ResponseRecorder {
		t.Helper()
		raw := []byte(body)
		token, err := signer.Sign(method, path, raw, protocol.Viewer{Subject: "admin", Role: "admin"}, time.Now())
		if err != nil {
			t.Fatal(err)
		}
		r := httptest.NewRequest(method, path, strings.NewReader(body))
		r.Header.Set(protocol.Header, token)
		w := httptest.NewRecorder()
		server.ServeHTTP(w, r)
		return w
	}
	w := call("PUT", "/v1/manage/settings", `{"public_enabled":false,"probes_paused":true,"outbox_paused":true,"portal_url":"https://portal.example","portal_networks":[]}`)
	if w.Code != 200 {
		t.Fatalf("settings=%d %s", w.Code, w.Body.String())
	}
	w = call("GET", "/v1/manage/operations", "")
	if w.Code != 200 {
		t.Fatalf("operations=%d %s", w.Code, w.Body.String())
	}
	var review struct {
		Fingerprint string `json:"queue_fingerprint"`
	}
	json.Unmarshal(w.Body.Bytes(), &review)
	w = call("POST", "/v1/manage/resume", `{"queue_fingerprint":"`+review.Fingerprint+`","probes":true,"outbox":true}`)
	if w.Code != 200 {
		t.Fatal("reviewed resume failed")
	}
	if store.Settings().ProbesPaused || store.Settings().OutboxPaused {
		t.Fatal("resume did not clear pause")
	}
	w = call("GET", "/v1/incidents?limit=50", "")
	if w.Code != 200 {
		t.Fatalf("incidents=%d %s", w.Code, w.Body.String())
	}
	w = call("GET", "/v1/incidents?limit=10000", "")
	if w.Code != 400 {
		t.Fatal("unbounded history allowed")
	}
}
