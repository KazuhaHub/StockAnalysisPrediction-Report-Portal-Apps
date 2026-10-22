package status

import (
	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
	"time"
)

// RequestProbe schedules existing validated configuration. It never bypasses
// worker limits, paused operation, leases or the credential revision fence.
func (s *Store) RequestProbe(v protocol.Viewer, id string, revision int64) error {
	if !isAdmin(v) {
		return ErrForbidden
	}
	if id == "" || revision < 1 {
		return ErrInvalid
	}
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	var paused string
	if err := tx.QueryRow(`SELECT COALESCE((SELECT value FROM settings WHERE key='probes_paused'),'0')`).Scan(&paused); err != nil {
		return err
	}
	if paused == "1" {
		return ErrConflict
	}
	now := time.Now().UnixMilli()
	var recent int
	if err := tx.QueryRow(`SELECT COUNT(*) FROM audit_events WHERE target_id=? AND action='monitor.check' AND created_at>?`, id, now-30000).Scan(&recent); err != nil {
		return err
	}
	if recent > 0 {
		return ErrConflict
	}
	result, err := tx.Exec(`UPDATE monitors SET next_at=? WHERE id=? AND revision=? AND enabled=1 AND lease_token='' AND EXISTS(SELECT 1 FROM components p WHERE p.id=monitors.component_id AND p.enabled=1)`, now, id, revision)
	if err != nil {
		return err
	}
	count, err := result.RowsAffected()
	if err != nil {
		return err
	}
	if count != 1 {
		return ErrConflict
	}
	if err := audit(tx, v, "monitor.check", id, now); err != nil {
		return err
	}
	return tx.Commit()
}
