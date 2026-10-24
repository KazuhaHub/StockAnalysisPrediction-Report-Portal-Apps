package status

import (
	"testing"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

func TestPublicationDestinationChangeRequiresPairingReview(t *testing.T) {
	s, component := outboxFixture(t)
	admin := protocol.Viewer{Subject: "admin", Role: "admin"}
	if err := s.SaveSettings(admin, ServiceSettings{PortalURL: "https://another.example"}); err != nil {
		t.Fatal(err)
	}
	var enabled int
	s.db.QueryRow(`SELECT enabled FROM notification_publishers WHERE component_id=?`, component).Scan(&enabled)
	if enabled != 0 {
		t.Fatal("destination changed without publisher review")
	}
	var state string
	s.db.QueryRow(`SELECT state FROM notification_outbox WHERE component_id=?`, component).Scan(&state)
	if state != "review_required" {
		t.Fatal("pending payload retargeted")
	}
	if _, ok, err := s.ClaimNotice(time.Now().Add(time.Hour)); err != nil || ok {
		t.Fatal("old message silently retargeted")
	}
}
func TestCleanupRetainsActiveIncidentsAndPendingNotices(t *testing.T) {
	s, _ := outboxFixture(t)
	future := time.Now().Add(120 * 24 * time.Hour)
	if err := s.Cleanup(future); err != nil {
		t.Fatal(err)
	}
	var incidents, notices, observations int
	s.db.QueryRow(`SELECT COUNT(*) FROM incidents`).Scan(&incidents)
	s.db.QueryRow(`SELECT COUNT(*) FROM notification_outbox`).Scan(&notices)
	s.db.QueryRow(`SELECT COUNT(*) FROM observations`).Scan(&observations)
	if incidents != 1 || notices != 1 || observations != 3 {
		t.Fatalf("active evidence purged: %d %d %d", incidents, notices, observations)
	}
}
