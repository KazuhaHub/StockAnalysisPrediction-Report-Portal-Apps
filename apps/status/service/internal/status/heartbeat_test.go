package status

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

func TestHeartbeatAuthenticatesAndPersistsReplayFence(t *testing.T) {
	s := testStore(t)
	admin := protocol.Viewer{Subject: "admin", Role: "admin"}
	credential, err := s.SaveCredential(admin, CredentialInput{Kind: "heartbeat", Label: "Backup job", Secret: json.RawMessage(`{"api_key":"heartbeat-secret-at-least-32-bytes"}`)})
	if err != nil {
		t.Fatal(err)
	}
	component, err := s.SaveComponent(admin, ComponentInput{Label: "Backup age", Enabled: true, Monitors: []MonitorInput{{Kind: "heartbeat", Label: "Backup heartbeat", CredentialID: credential.ID, Config: json.RawMessage(`{}`), Enabled: true, IntervalSeconds: 3600, TimeoutSeconds: 5}}})
	if err != nil {
		t.Fatal(err)
	}
	signer := protocol.Signer{Issuer: "portal", Audience: "status", AppID: "status", InstanceID: "one", KeyID: "key", Key: []byte(strings.Repeat("k", 32))}
	server, err := NewServer(s, signer)
	if err != nil {
		t.Fatal(err)
	}
	monitor := component.Monitors[0].ID
	raw := `{"timestamp":"` + time.Now().UTC().Format(time.RFC3339) + `","nonce":"external-job-nonce"}`
	mac := hmac.New(sha256.New, []byte("heartbeat-secret-at-least-32-bytes"))
	mac.Write([]byte(monitor + "\n" + raw))
	signature := hex.EncodeToString(mac.Sum(nil))
	call := func(sig string) *httptest.ResponseRecorder {
		r := httptest.NewRequest("POST", "/ingest/v1/heartbeats/"+monitor, strings.NewReader(raw))
		r.Header.Set("X-Status-Signature", sig)
		w := httptest.NewRecorder()
		server.ServeHTTP(w, r)
		return w
	}
	if w := call("wrong"); w.Code != 401 {
		t.Fatal("unsigned heartbeat accepted")
	}
	if w := call(signature); w.Code != 202 {
		t.Fatalf("heartbeat=%d %s", w.Code, w.Body.String())
	}
	if w := call(signature); w.Code != 401 {
		t.Fatal("replayed heartbeat accepted")
	}
	now := time.Now().Add(time.Minute)
	m, ok, err := s.ClaimDue(now)
	if err != nil || !ok {
		t.Fatal("heartbeat monitor not claimable")
	}
	result := s.HeartbeatResult(m, now)
	if result.Outcome != "success" {
		t.Fatalf("heartbeat not observed: %+v", result)
	}
	if result := s.HeartbeatResult(m, now.Add(4*time.Hour)); result.Outcome != "failure" {
		t.Fatal("missed heartbeat stayed healthy")
	}
}
