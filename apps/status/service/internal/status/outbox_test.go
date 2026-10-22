package status

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

func outboxFixture(t *testing.T) (*Store, string) {
	t.Helper()
	s := testStore(t)
	c := monitoredComponent(t, s)
	admin := protocol.Viewer{Subject: "admin", Role: "admin"}
	cred, err := s.SaveCredential(admin, CredentialInput{Kind: "notification", Label: "Publisher", Secret: json.RawMessage(`{"token":"dedicated-notification-token"}`)})
	if err != nil {
		t.Fatal(err)
	}
	if err := s.SavePublisher(admin, PublisherInput{ComponentID: c.ID, PublisherName: "status-" + c.ID, CredentialID: cred.ID, Enabled: true}); err != nil {
		t.Fatal(err)
	}
	now := time.Now().Add(time.Minute)
	for range 3 {
		m, ok, err := s.ClaimDue(now)
		if err != nil || !ok {
			t.Fatal("probe claim failed")
		}
		if err := s.Record(m, Result{Outcome: "failure", ReasonCode: "network_unavailable"}, now); err != nil {
			t.Fatal(err)
		}
		now = now.Add(2 * time.Minute)
	}
	return s, c.ID
}
func TestOutboxRetriesImmutableOccurrenceAndFencesChanges(t *testing.T) {
	s, component := outboxFixture(t)
	now := time.Now().Add(time.Hour)
	item, ok, err := s.ClaimNotice(now)
	if err != nil || !ok {
		t.Fatalf("claim=%v %v", ok, err)
	}
	original := item.Payload
	if !strings.Contains(original, "status:"+component+":") {
		t.Fatal("occurrence lacks component and incident identity")
	}
	if strings.Contains(original, "health.example") || strings.Contains(original, "token") {
		t.Fatal("notification exposed private configuration")
	}
	if err := s.FinishNotice(item, PublishResult{ErrorCode: "timeout"}, now); err != nil {
		t.Fatal(err)
	}
	retry, ok, err := s.ClaimNotice(now.Add(time.Hour))
	if err != nil || !ok || retry.Payload != original || retry.OccurrenceID != item.OccurrenceID {
		t.Fatal("retry changed immutable event identity")
	}
	if _, err := s.db.Exec(`UPDATE notification_publishers SET revision=revision+1 WHERE component_id=?`, component); err != nil {
		t.Fatal(err)
	}
	if s.NoticeCurrent(retry) {
		t.Fatal("publisher change did not fence claimed notice")
	}
	if err := s.FinishNotice(retry, PublishResult{EventID: "captured"}, now.Add(time.Hour)); err != ErrConflict {
		t.Fatal("old publisher acknowledgement applied")
	}
}
func TestPublisherReturnsCaptureNotDeliveryAndUsesFixedPath(t *testing.T) {
	s, _ := outboxFixture(t)
	item, ok, err := s.ClaimNotice(time.Now().Add(time.Hour))
	if err != nil || !ok {
		t.Fatal("notice unavailable")
	}
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "GET" && r.URL.Path == "/api/v1/notifications/publisher" {
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(map[string]any{"ok": true, "publisher": "service.status-" + item.ComponentID})
			return
		}
		if r.URL.Path != "/api/v1/notifications" || r.Method != "POST" || r.Header.Get("Authorization") != "Bearer dedicated-notification-token" {
			t.Error("unexpected publication authority")
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"ok":true,"id":"event-one"}`))
	}))
	defer upstream.Close()
	sender := &Publisher{URL: "https://portal.example", clientForTest: func(ProbeConfig) (*http.Client, error) {
		return &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
			r.URL.Scheme = "http"
			r.URL.Host = strings.TrimPrefix(upstream.URL, "http://")
			return http.DefaultTransport.RoundTrip(r)
		})}, nil
	}}
	result := sender.Publish(context.Background(), item)
	if result.EventID != "event-one" || result.ErrorCode != "" {
		t.Fatalf("capture=%+v", result)
	}
}
func TestRestoreQueueFingerprintRejectsConcurrentChange(t *testing.T) {
	s, _ := outboxFixture(t)
	admin := protocol.Viewer{Subject: "admin", Role: "admin"}
	s.db.Exec(`INSERT INTO settings(key,value) VALUES('outbox_paused','1')`)
	fingerprint, err := s.QueueFingerprint()
	if err != nil {
		t.Fatal(err)
	}
	s.db.Exec(`UPDATE notification_outbox SET attempts=attempts+1`)
	if err := s.Resume(admin, fingerprint, true, true); err != ErrConflict {
		t.Fatalf("unreviewed queue resumed: %v", err)
	}
}

func TestWrongPublisherNamespaceNeverSendsNotice(t *testing.T) {
	s, _ := outboxFixture(t)
	notice, ok, err := s.ClaimNotice(time.Now().Add(time.Hour))
	if err != nil || !ok {
		t.Fatal("claim failed")
	}
	sent := false
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "POST" {
			sent = true
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"ok":true,"publisher":"service.status-foreign"}`))
	}))
	defer upstream.Close()
	publisher := Publisher{URL: "https://portal.example", clientForTest: func(ProbeConfig) (*http.Client, error) {
		return &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
			r.URL.Scheme = "http"
			r.URL.Host = strings.TrimPrefix(upstream.URL, "http://")
			return http.DefaultTransport.RoundTrip(r)
		})}, nil
	}}
	result := publisher.Publish(context.Background(), notice)
	if sent || !result.Conflict || result.ErrorCode != "rejected" {
		t.Fatal("mismatched publisher sent private notice")
	}
}
