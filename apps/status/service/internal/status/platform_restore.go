package status

import (
	"errors"
	"time"
)

// ReconcilePlatform compares the platform identity of this boot with the one
// recorded in the data. The platform restores and migrates /data itself, so the
// service cannot be told that a restore happened. It can only see that the data
// was written under a different installation or controller epoch, or under none.
//
// A new installation records the identity and changes nothing else. Existing
// data under a different or missing identity is treated as restored: probes and
// notification delivery stay paused until an administrator reviews the queue and
// resumes them, exactly as after a first start.
//
// It must run before any worker or HTTP route starts.
func (s *Store) ReconcilePlatform(identity string, now time.Time) (restored bool, err error) {
	if identity == "" || len(identity) > 256 {
		return false, errors.New("platform identity is required")
	}
	recorded := s.setting("platform_identity")
	if recorded == identity {
		return false, nil
	}
	var rows int
	if err := s.db.QueryRow(`SELECT (SELECT COUNT(*) FROM components)+(SELECT COUNT(*) FROM credentials)+(SELECT COUNT(*) FROM incidents)+(SELECT COUNT(*) FROM notification_outbox)`).Scan(&rows); err != nil {
		return false, err
	}
	tx, err := s.db.Begin()
	if err != nil {
		return false, err
	}
	defer tx.Rollback()
	if rows > 0 {
		at := now.UnixMilli()
		if err := closeEvidence(tx, "1=1", nil, at); err != nil {
			return false, err
		}
		for _, key := range []string{"probes_paused", "outbox_paused"} {
			if err := setSetting(tx, key, "1"); err != nil {
				return false, err
			}
		}
		statements := []string{
			`INSERT INTO settings(key,value) VALUES('public_enabled','0') ON CONFLICT(key) DO UPDATE SET value='0'`,
			`UPDATE monitors SET lease_token='',lease_until=0,revision=revision+1`,
			`UPDATE notification_outbox SET state=CASE WHEN attempts>0 OR state='leased' THEN 'review_required' ELSE state END,lease_token='',lease_until=0 WHERE state<>'delivered'`,
			`UPDATE notification_publishers SET enabled=0,revision=revision+1`,
		}
		for _, q := range statements {
			if _, err := tx.Exec(q); err != nil {
				return false, err
			}
		}
		if _, err := tx.Exec(`UPDATE monitor_states SET current_state='unknown',success_streak=0,failure_streak=0,updated_at=?`, at); err != nil {
			return false, err
		}
		if _, err := tx.Exec(`INSERT INTO audit_events(id,actor,action,target_id,safe_detail,created_at) VALUES(?,'platform','platform.restore','service','{}',?)`, newID(), at); err != nil {
			return false, err
		}
		if _, err := tx.Exec(`INSERT INTO audit_events(id,actor,action,target_id,safe_detail,created_at) VALUES(?,'platform','probes.pause','service','{}',?)`, newID(), at); err != nil {
			return false, err
		}
	}
	if err := setSetting(tx, "platform_identity", identity); err != nil {
		return false, err
	}
	if err := tx.Commit(); err != nil {
		return false, err
	}
	return rows > 0, nil
}
