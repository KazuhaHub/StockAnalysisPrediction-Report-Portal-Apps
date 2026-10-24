package status

import (
	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
	"testing"
	"time"
)

func TestRetentionPolicyBoundsAndCleanupRespectConfiguredDurations(t *testing.T) {
	s := testStore(t)
	admin := protocol.Viewer{Subject: "admin", Role: "admin"}
	settings := s.Settings()
	if settings.RawRetentionDays != 30 || settings.HistoryRetentionDays != 90 {
		t.Fatalf("unexpected defaults=%+v", settings)
	}
	invalid := settings
	invalid.RawRetentionDays = 31
	if err := s.SaveSettings(admin, invalid); err != ErrInvalid {
		t.Fatal("unbounded raw retention accepted")
	}
	invalid = settings
	invalid.RawRetentionDays = 10
	invalid.HistoryRetentionDays = 5
	if err := s.SaveSettings(admin, invalid); err != ErrInvalid {
		t.Fatal("history shorter than raw accepted")
	}
	settings.RawRetentionDays = 2
	settings.HistoryRetentionDays = 7
	if err := s.SaveSettings(admin, settings); err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC().Truncate(time.Hour)
	_, id := seedHistoryMonitor(t, s, now.Add(-10*24*time.Hour))
	for _, days := range []int{1, 3} {
		if _, err := s.db.Exec(`INSERT INTO observations(id,monitor_id,monitor_revision,outcome,reason_code,measurements,observed_at,duration_ms) VALUES(?,?,1,'unknown','observer_unavailable','{}',?,0)`, newID(), id, now.Add(-time.Duration(days)*24*time.Hour).UnixMilli()); err != nil {
			t.Fatal(err)
		}
	}
	for _, days := range []int{6, 8} {
		if _, err := s.db.Exec(`INSERT INTO hourly_aggregates VALUES(?,?,0,0,0,3600000,0)`, id, now.Add(-time.Duration(days)*24*time.Hour).UnixMilli()); err != nil {
			t.Fatal(err)
		}
	}
	if err := s.Cleanup(now); err != nil {
		t.Fatal(err)
	}
	var raw, hours int
	s.db.QueryRow(`SELECT COUNT(*) FROM observations WHERE monitor_id=?`, id).Scan(&raw)
	s.db.QueryRow(`SELECT COUNT(*) FROM hourly_aggregates WHERE monitor_id=?`, id).Scan(&hours)
	if raw != 1 || hours != 1 {
		t.Fatalf("policy ignored raw=%d hours=%d", raw, hours)
	}
	restored := s.Settings()
	if restored.RawRetentionDays != 2 || restored.HistoryRetentionDays != 7 {
		t.Fatal("retention settings not persisted")
	}
	if err := s.SaveSettings(protocol.Viewer{Role: "user", Subject: "reader"}, settings); err != ErrForbidden {
		t.Fatal("reader changed retention")
	}
}
