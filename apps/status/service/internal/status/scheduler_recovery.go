package status

import (
	"database/sql"
	"encoding/json"
	"errors"
	"time"
)

// Recover one abandoned check per scheduler tick. The lease boundary records
// observer failure, not target failure, and a future due time bounds catch-up.
func recoverExpiredProbe(tx *sql.Tx, now time.Time) (bool, error) {
	var m Monitor
	var expired, updated int64
	var state string
	err := tx.QueryRow(`SELECT m.id,m.component_id,m.revision,m.interval_seconds,m.timeout_seconds,m.lease_until,s.current_state,s.updated_at FROM monitors m JOIN monitor_states s ON s.monitor_id=m.id WHERE m.lease_token<>'' AND m.lease_until<=? ORDER BY m.lease_until,m.id LIMIT 1`, now.UnixMilli()).Scan(&m.ID, &m.ComponentID, &m.Revision, &m.IntervalSeconds, &m.TimeoutSeconds, &expired, &state, &updated)
	if errors.Is(err, sql.ErrNoRows) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	if expired < updated {
		return false, ErrConflict
	}
	if err := aggregateInterval(tx, m, updated, expired, state); err != nil {
		return false, err
	}
	evidence, err := json.Marshal(recordedMeasurements{State: observationState{Version: 1, State: "unknown", FreshUntil: expired}})
	if err != nil {
		return false, err
	}
	observation := newID()
	if _, err := tx.Exec(`INSERT INTO observations(id,monitor_id,monitor_revision,outcome,reason_code,measurements,observed_at,duration_ms) VALUES(?,?,?,'unknown','observer_unavailable',?,?,0)`, observation, m.ID, m.Revision, string(evidence), expired); err != nil {
		return false, err
	}
	if _, err := tx.Exec(`UPDATE monitor_states SET revision=revision+1,current_state='unknown',success_streak=0,failure_streak=0,last_observation_id=?,updated_at=? WHERE monitor_id=?`, observation, expired, m.ID); err != nil {
		return false, err
	}
	jitter := int64(m.ID[0]) % int64(max(1, m.IntervalSeconds/10))
	if _, err := tx.Exec(`UPDATE monitors SET lease_token='',lease_until=0,next_at=? WHERE id=?`, now.Add(time.Duration(int64(m.IntervalSeconds)+jitter)*time.Second).UnixMilli(), m.ID); err != nil {
		return false, err
	}
	return true, nil
}
