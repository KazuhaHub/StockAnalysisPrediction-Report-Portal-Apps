package status

import (
	"encoding/json"
	"path/filepath"
	"testing"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

func recoveryNotice(t *testing.T, s *Store, start time.Time) (ComponentInput, string) {
	t.Helper()
	c, id := seedHistoryMonitor(t, s, start)
	admin := protocol.Viewer{Subject: "admin", Role: "admin"}
	credential, err := s.SaveCredential(admin, CredentialInput{Kind: "notification", Label: "Recovery publisher", Secret: json.RawMessage(`{"token":"fixture-publisher-token"}`)})
	if err != nil {
		t.Fatal(err)
	}
	if err := s.SavePublisher(admin, PublisherInput{ComponentID: c.ID, PublisherName: "status-" + c.ID, CredentialID: credential.ID, Enabled: true}); err != nil {
		t.Fatal(err)
	}
	for i := 1; i <= 3; i++ {
		at := start.Add(time.Duration(i*2) * time.Minute)
		m, ok, err := s.ClaimDue(at)
		if err != nil || !ok || m.ID != id {
			t.Fatalf("claim=%v %v", ok, err)
		}
		if err := s.Record(m, Result{Outcome: "failure", ReasonCode: "network_unavailable"}, at); err != nil {
			t.Fatal(err)
		}
	}
	return c, id
}

func TestOutboxExpiredLeaseAfterRestartKeepsOccurrence(t *testing.T) {
	s := testStore(t)
	recoveryNotice(t, s, time.Now().Add(-20*time.Minute))
	now := time.Now()
	first, ok, err := s.ClaimNotice(now)
	if err != nil || !ok {
		t.Fatalf("first claim=%v %v", ok, err)
	}
	// Simulate an acknowledgement lost after Portal durably captured the event.
	if err := s.db.Close(); err != nil {
		t.Fatal(err)
	}
	if err := s.openDB(); err != nil {
		t.Fatal(err)
	}
	if _, ok, err := s.ClaimNotice(now.Add(20 * time.Second)); err != nil || ok {
		t.Fatalf("unexpired lease reclaimed=%v %v", ok, err)
	}
	retry, ok, err := s.ClaimNotice(now.Add(time.Minute))
	if err != nil || !ok {
		t.Fatalf("retry claim=%v %v", ok, err)
	}
	if retry.ID != first.ID || retry.OccurrenceID != first.OccurrenceID || retry.Payload != first.Payload || retry.Lease == first.Lease || retry.Attempts != 2 {
		t.Fatalf("restart changed immutable notice or lease")
	}
	if err := s.FinishNotice(first, PublishResult{EventID: "stale-ack"}, now.Add(time.Minute)); err != ErrConflict {
		t.Fatalf("old acknowledgement accepted: %v", err)
	}
	if err := s.FinishNotice(retry, PublishResult{EventID: "original-portal-event"}, now.Add(time.Minute)); err != nil {
		t.Fatal(err)
	}
	if _, ok, err := s.ClaimNotice(now.Add(2 * time.Minute)); err != nil || ok {
		t.Fatalf("captured event reclaimed=%v %v", ok, err)
	}
}

func TestRestoreUncertainPublicationRequiresExplicitDiscard(t *testing.T) {
	s := testStore(t)
	c, _ := recoveryNotice(t, s, time.Now().Add(-20*time.Minute))
	first, ok, err := s.ClaimNotice(time.Now())
	if err != nil || !ok {
		t.Fatalf("claim=%v %v", ok, err)
	}
	backup := filepath.Join(t.TempDir(), "uncertain.db")
	if err := s.Backup(backup); err != nil {
		t.Fatal(err)
	}
	if err := s.Restore(backup); err != nil {
		t.Fatal(err)
	}
	if s.NoticeCurrent(first) {
		t.Fatal("restored old lease retained authority")
	}
	admin := protocol.Viewer{Subject: "admin", Role: "admin"}
	fingerprint, err := s.QueueFingerprint()
	if err != nil {
		t.Fatal(err)
	}
	if err := s.Resume(admin, fingerprint, true, true); err != nil {
		t.Fatal(err)
	}
	if _, ok, err := s.ClaimNotice(time.Now().Add(time.Hour)); err != nil || ok {
		t.Fatalf("restored uncertainty auto-published=%v %v", ok, err)
	}
	var state string
	if err := s.db.QueryRow(`SELECT state FROM notification_outbox WHERE id=?`, first.ID).Scan(&state); err != nil || state != "review_required" {
		t.Fatalf("state=%s err=%v", state, err)
	}
	if err := s.ReviewNotice(admin, first.ID, fingerprint, "retry_same_publisher"); err != ErrConflict {
		t.Fatalf("restored publisher revision silently reused: %v", err)
	}
	if err := s.ReviewNotice(admin, first.ID, fingerprint, "discard"); err != nil {
		t.Fatal(err)
	}
	var payload, occurrence string
	if err := s.db.QueryRow(`SELECT payload,occurrence_id FROM notification_outbox WHERE id=? AND component_id=? AND state='discarded'`, first.ID, c.ID).Scan(&payload, &occurrence); err != nil || payload != first.Payload || occurrence != first.OccurrenceID {
		t.Fatal("discard lost reconciliation evidence")
	}
}

func TestNotificationStormPreservesTransitionsAndBoundsPublication(t *testing.T) {
	s := testStore(t)
	start := time.Now().Add(-40 * time.Minute)
	c, id := recoveryNotice(t, s, start)
	at := start.Add(7 * time.Minute)
	for cycle := 0; cycle < 5; cycle++ {
		for _, outcome := range []string{"success", "success", "failure", "failure", "failure"} {
			at = at.Add(2 * time.Minute)
			m, ok, err := s.ClaimDue(at)
			if err != nil || !ok || m.ID != id {
				t.Fatalf("claim=%v %v", ok, err)
			}
			reason := "reachable"
			if outcome == "failure" {
				reason = "network_unavailable"
			}
			if err := s.Record(m, Result{Outcome: outcome, ReasonCode: reason}, at); err != nil {
				t.Fatal(err)
			}
		}
	}
	var notices, transitions, suppressed int
	for _, q := range []struct {
		query  string
		target *int
	}{
		{`SELECT COUNT(*) FROM notification_outbox WHERE component_id=?`, &notices},
		{`SELECT COUNT(*) FROM incident_transitions t JOIN incidents i ON i.id=t.incident_id WHERE i.component_id=?`, &transitions},
		{`SELECT COUNT(*) FROM audit_events WHERE action='notice.suppressed' AND target_id=?`, &suppressed},
	} {
		if err := s.db.QueryRow(q.query, c.ID).Scan(q.target); err != nil {
			t.Fatal(err)
		}
	}
	if notices != 5 || transitions != 11 || suppressed != 6 {
		t.Fatalf("notices=%d transitions=%d suppressed=%d", notices, transitions, suppressed)
	}
}
