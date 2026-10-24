package status

import (
	"bytes"
	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
	"path/filepath"
	"testing"
	"time"
)

func TestFirstStartRequiresExplicitResumeBeforeProbing(t *testing.T) {
	s, err := Open(filepath.Join(t.TempDir(), "new.db"), bytes.Repeat([]byte{7}, 32))
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	settings := s.Settings()
	if !settings.ProbesPaused || !settings.OutboxPaused || settings.PublicEnabled {
		t.Fatalf("new service started without operator review: %+v", settings)
	}
	component := monitoredComponent(t, s)
	now := time.Now()
	if _, err := s.db.Exec(`UPDATE audit_events SET created_at=? WHERE actor='bootstrap' AND action='probes.pause'`, now.Add(-10*time.Minute).UnixMilli()); err != nil {
		t.Fatal(err)
	}
	if _, err := s.db.Exec(`UPDATE monitors SET created_at=? WHERE component_id=?`, now.Add(-9*time.Minute).UnixMilli(), component.ID); err != nil {
		t.Fatal(err)
	}
	history, err := s.History(protocol.Viewer{Subject: "admin", Role: "admin"}, component.ID, now.Add(-8*time.Minute), now.Add(-7*time.Minute))
	if err != nil || len(history) != 1 || history[0].ExcludedMS != 60000 {
		t.Fatalf("first-start pause did not exclude history=%+v %v", history, err)
	}
	if _, ok, err := s.ClaimDue(time.Now().Add(time.Second)); err != nil || ok {
		t.Fatal("newly configured monitor ran before resume")
	}
	fingerprint, err := s.QueueFingerprint()
	if err != nil {
		t.Fatal(err)
	}
	if err := s.Resume(protocol.Viewer{Subject: "admin", Role: "admin"}, fingerprint, true, false); err != nil {
		t.Fatal(err)
	}
	if _, ok, err := s.ClaimDue(time.Now().Add(time.Second)); err != nil || !ok {
		t.Fatalf("reviewed probes did not start=%v %v", ok, err)
	}
	if !s.Settings().OutboxPaused {
		t.Fatal("probe resume silently started notification publication")
	}
}
