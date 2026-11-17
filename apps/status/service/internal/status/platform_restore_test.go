package status

import (
	"testing"
	"time"
)

func TestFreshInstallRecordsPlatformIdentityWithoutRestoreHandling(t *testing.T) {
	s, err := Open(t.TempDir()+"/status.db", []byte("0123456789abcdef0123456789abcdef"))
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	restored, err := s.ReconcilePlatform("installation-a/epoch-1", time.Now())
	if err != nil || restored {
		t.Fatalf("fresh install restored=%v err=%v", restored, err)
	}
	if s.setting("platform_identity") != "installation-a/epoch-1" {
		t.Fatal("platform identity not recorded")
	}
	var audits int
	s.db.QueryRow(`SELECT COUNT(*) FROM audit_events WHERE action='platform.restore'`).Scan(&audits)
	if audits != 0 {
		t.Fatal("fresh install audited as a restore")
	}
}

func TestSameIdentityRestartKeepsRunningWork(t *testing.T) {
	s := testStore(t)
	if restored, err := s.ReconcilePlatform("installation-a/epoch-1", time.Now()); err != nil || restored {
		t.Fatalf("empty store restored=%v err=%v", restored, err)
	}
	monitoredComponent(t, s)
	if restored, err := s.ReconcilePlatform("installation-a/epoch-1", time.Now()); err != nil || restored {
		t.Fatalf("restart restored=%v err=%v", restored, err)
	}
	if s.setting("probes_paused") == "1" || s.setting("outbox_paused") == "1" {
		t.Fatal("an ordinary restart paused reviewed work")
	}
}

func TestPlatformRestorePausesWorkUntilAdministratorResumes(t *testing.T) {
	s := testStore(t)
	if _, err := s.ReconcilePlatform("installation-a/epoch-1", time.Now()); err != nil {
		t.Fatal(err)
	}
	c, id := recoveryNotice(t, s, time.Now().Add(-20*time.Minute))
	first, ok, err := s.ClaimNotice(time.Now())
	if err != nil || !ok {
		t.Fatalf("claim=%v %v", ok, err)
	}
	if _, ok, err := s.ClaimDue(time.Now()); err != nil {
		t.Fatal(err)
	} else if !ok {
		t.Fatal("monitor was not leased")
	}
	if _, err := s.db.Exec(`INSERT INTO settings(key,value) VALUES('public_enabled','1')`); err != nil {
		t.Fatal(err)
	}
	restored, err := s.ReconcilePlatform("installation-a/epoch-2", time.Now())
	if err != nil || !restored {
		t.Fatalf("restored=%v err=%v", restored, err)
	}
	if s.setting("probes_paused") != "1" || s.setting("outbox_paused") != "1" || s.setting("public_enabled") != "0" {
		t.Fatal("restored work resumed without review")
	}
	if s.setting("platform_identity") != "installation-a/epoch-2" {
		t.Fatal("new platform identity not recorded")
	}
	if s.NoticeCurrent(first) {
		t.Fatal("restored lease retained publishing authority")
	}
	var leased int
	s.db.QueryRow(`SELECT COUNT(*) FROM monitors WHERE id=? AND lease_token<>''`, id).Scan(&leased)
	if leased != 0 {
		t.Fatal("restored monitor lease retained")
	}
	var state string
	s.db.QueryRow(`SELECT state FROM notification_outbox WHERE id=?`, first.ID).Scan(&state)
	if state != "review_required" {
		t.Fatalf("in-flight notice state=%s", state)
	}
	var enabled int
	s.db.QueryRow(`SELECT enabled FROM notification_publishers WHERE component_id=?`, c.ID).Scan(&enabled)
	if enabled != 0 {
		t.Fatal("restored publisher still enabled")
	}
	var audits int
	s.db.QueryRow(`SELECT COUNT(*) FROM audit_events WHERE actor='platform' AND action='platform.restore'`).Scan(&audits)
	if audits != 1 {
		t.Fatalf("restore audits=%d", audits)
	}
	if _, ok, err := s.ClaimDue(time.Now().Add(time.Hour)); err != nil || ok {
		t.Fatalf("paused probes claimed=%v %v", ok, err)
	}
	if _, ok, err := s.ClaimNotice(time.Now().Add(time.Hour)); err != nil || ok {
		t.Fatalf("paused outbox claimed=%v %v", ok, err)
	}
	fingerprint, err := s.QueueFingerprint()
	if err != nil {
		t.Fatal(err)
	}
	if err := s.Resume(fixtureViewer("user", "reader"), fingerprint, true, false); err != ErrForbidden {
		t.Fatalf("non-administrator resume=%v", err)
	}
	if err := s.Resume(fixtureAdmin(), fingerprint, true, false); err != nil {
		t.Fatal(err)
	}
	if s.setting("probes_paused") == "1" {
		t.Fatal("administrator could not resume probes")
	}
	if s.setting("outbox_paused") != "1" {
		t.Fatal("probe resume started notification delivery")
	}
}

func TestDataWithoutPlatformRecordIsTreatedAsRestored(t *testing.T) {
	s := testStore(t)
	monitoredComponent(t, s)
	restored, err := s.ReconcilePlatform("installation-a/epoch-1", time.Now())
	if err != nil || !restored {
		t.Fatalf("restored=%v err=%v", restored, err)
	}
	if s.setting("probes_paused") != "1" || s.setting("outbox_paused") != "1" {
		t.Fatal("unrecorded data started without review")
	}
}

func TestReconcileRejectsAnEmptyIdentity(t *testing.T) {
	s := testStore(t)
	if _, err := s.ReconcilePlatform("", time.Now()); err == nil {
		t.Fatal("empty platform identity accepted")
	}
}
