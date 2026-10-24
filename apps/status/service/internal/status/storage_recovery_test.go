package status

import (
	"bytes"
	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
	"os"
	"path/filepath"
	"testing"
)

func TestRestoreRejectsIncompatibleCandidatesWithoutReplacingLiveData(t *testing.T) {
	for _, scenario := range []string{"wrong-key", "future-schema", "missing-product", "occupied-rollback"} {
		t.Run(scenario, func(t *testing.T) {
			live := testStore(t)
			admin := protocol.Viewer{Subject: "admin", Role: "admin"}
			component, err := live.SaveComponent(admin, ComponentInput{Label: "Must survive", Enabled: true})
			if err != nil {
				t.Fatal(err)
			}
			candidatePath := filepath.Join(t.TempDir(), "candidate.db")
			key := bytes.Repeat([]byte{7}, 32)
			if scenario == "wrong-key" {
				key = bytes.Repeat([]byte{8}, 32)
			}
			candidate, err := Open(candidatePath, key)
			if err != nil {
				t.Fatal(err)
			}
			if scenario == "future-schema" {
				if _, err := candidate.db.Exec(`INSERT INTO schema_migrations VALUES(2,1)`); err != nil {
					t.Fatal(err)
				}
			}
			if scenario == "missing-product" {
				if _, err := candidate.db.Exec(`DROP INDEX idx_observations_time`); err != nil {
					t.Fatal(err)
				}
			}
			if err := candidate.Close(); err != nil {
				t.Fatal(err)
			}
			if scenario == "occupied-rollback" {
				if err := os.WriteFile(live.path+".pre-restore", []byte("retained rollback"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			if err := live.Restore(candidatePath); err == nil {
				t.Fatal("incompatible restore accepted")
			}
			var label string
			if err := live.db.QueryRow(`SELECT label FROM components WHERE id=?`, component.ID).Scan(&label); err != nil || label != "Must survive" {
				t.Fatalf("live data replaced: %s %v", label, err)
			}
			component.Label = "Still writable"
			if _, err := live.SaveComponent(admin, component); err != nil {
				t.Fatalf("rejected restore left live database unavailable: %v", err)
			}
			if live.setting("probes_paused") == "1" {
				t.Fatal("candidate pause settings leaked into live database")
			}
		})
	}
}
