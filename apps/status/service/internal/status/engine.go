package status

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"strconv"
	"sync"
	"time"
)

func (s *Store) ClaimDue(now time.Time) (Monitor, bool, error) {
	var m Monitor
	if s.setting("probes_paused") == "1" {
		return m, false, nil
	}
	tx, err := s.db.Begin()
	if err != nil {
		return m, false, err
	}
	defer tx.Rollback()
	if recovered, err := recoverExpiredProbe(tx, now); err != nil {
		return m, false, err
	} else if recovered {
		return m, false, tx.Commit()
	}
	var config, sealed, credentialKind string
	err = tx.QueryRow(`SELECT m.id,m.component_id,m.kind,m.label,COALESCE(m.credential_id,''),m.revision,m.interval_seconds,m.timeout_seconds,m.config,COALESCE(c.revision,0),COALESCE(c.sealed_value,''),COALESCE(c.kind,'') FROM monitors m JOIN components p ON p.id=m.component_id LEFT JOIN credentials c ON c.id=m.credential_id WHERE m.enabled=1 AND p.enabled=1 AND m.next_at<=? AND m.lease_until<=? AND (m.credential_id IS NULL OR NOT EXISTS(SELECT 1 FROM monitors busy WHERE busy.credential_id=m.credential_id AND busy.lease_until>?)) ORDER BY m.next_at,m.id LIMIT 1`, now.UnixMilli(), now.UnixMilli(), now.UnixMilli()).Scan(&m.ID, &m.ComponentID, &m.Kind, &m.Label, &m.CredentialID, &m.Revision, &m.IntervalSeconds, &m.TimeoutSeconds, &config, &m.CredentialRevision, &sealed, &credentialKind)
	if errors.Is(err, sql.ErrNoRows) {
		return m, false, nil
	}
	if err != nil {
		return m, false, err
	}
	if json.Unmarshal([]byte(config), &m.Config) != nil {
		return m, false, ErrInvalid
	}
	if m.CredentialID != "" {
		plain, err := s.open(m.CredentialID, credentialKind, sealed)
		if err != nil {
			return m, false, err
		}
		if json.Unmarshal(plain, &m.Secret) != nil {
			return m, false, ErrInvalid
		}
	}
	m.Lease = newID()
	leaseUntil := now.Add(time.Duration(m.TimeoutSeconds+10) * time.Second).UnixMilli()
	result, err := tx.Exec(`UPDATE monitors SET lease_token=?,lease_until=? WHERE id=? AND revision=? AND lease_until<=? AND next_at<=?`, m.Lease, leaseUntil, m.ID, m.Revision, now.UnixMilli(), now.UnixMilli())
	if err != nil {
		return m, false, err
	}
	n, _ := result.RowsAffected()
	if n != 1 {
		return m, false, nil
	}
	if err := tx.Commit(); err != nil {
		return m, false, err
	}
	return m, true, nil
}

var safeReasons = map[string]bool{"reachable": true, "observer_unavailable": true, "heartbeat_not_received": true, "heartbeat_missed": true, "heartbeat_received": true, "network_unavailable": true, "invalid_destination": true, "unsupported_probe": true, "invalid_response": true, "authentication_failed": true, "rate_limited": true, "redirect_refused": true, "upstream_unavailable": true, "invalid_balance_response": true, "currency_unavailable": true, "balance_read": true, "low_balance": true, "low_credit": true, "insufficient_funds": true, "billing_unsupported": true, "billing_permission_required": true, "billing_site_mismatch": true, "billing_unavailable": true, "database_unavailable": true, "database_query_failed": true}

func (s *Store) Record(m Monitor, result Result, now time.Time) error {
	if !safeReasons[result.ReasonCode] || result.DurationMS < 0 || result.DurationMS > 60000 || result.RetryAfter < 0 || result.RetryAfter > time.Hour {
		return ErrInvalid
	}
	if result.Outcome != "success" && result.Outcome != "failure" && result.Outcome != "degraded" && result.Outcome != "unknown" && result.Outcome != "unsupported" && result.Outcome != "hold" {
		return ErrInvalid
	}
	metrics, err := json.Marshal(result.Measurements)
	if err != nil || len(metrics) > 8192 {
		return ErrInvalid
	}
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	var currentRevision, credentialRevision, leaseUntil int64
	var currentLease string
	var enabled, componentEnabled int
	err = tx.QueryRow(`SELECT m.revision,m.lease_token,m.lease_until,m.enabled,p.enabled,COALESCE(c.revision,0) FROM monitors m JOIN components p ON p.id=m.component_id LEFT JOIN credentials c ON c.id=m.credential_id WHERE m.id=?`, m.ID).Scan(&currentRevision, &currentLease, &leaseUntil, &enabled, &componentEnabled, &credentialRevision)
	if err != nil || currentRevision != m.Revision || currentLease != m.Lease || leaseUntil < now.UnixMilli() || enabled != 1 || componentEnabled != 1 || credentialRevision != m.CredentialRevision {
		return ErrConflict
	}
	var state string
	var success, failure int
	var lastSuccess, updated int64
	if err := tx.QueryRow(`SELECT current_state,success_streak,failure_streak,last_success_at,updated_at FROM monitor_states WHERE monitor_id=?`, m.ID).Scan(&state, &success, &failure, &lastSuccess, &updated); err != nil {
		return err
	}
	intervalState := state
	var maintenanceEnd int64
	if err := tx.QueryRow(`SELECT COALESCE(MAX(ends_at),0) FROM maintenance_windows WHERE component_id=? AND ends_at<=?`, m.ComponentID, now.UnixMilli()).Scan(&maintenanceEnd); err != nil {
		return err
	}
	if maintenanceEnd > updated {
		state = "unknown"
		success, failure = 0, 0
	}
	if now.UnixMilli()-updated > int64(max(3*m.IntervalSeconds, 2*m.TimeoutSeconds))*1000 {
		state = "unknown"
		success, failure = 0, 0
	}
	switch result.Outcome {
	case "success":
		success++
		failure = 0
		lastSuccess = now.UnixMilli()
		if success >= 2 {
			state = "operational"
		}
	case "failure":
		failure++
		success = 0
		if failure >= 3 {
			state = "outage"
		}
	case "degraded":
		failure++
		success = 0
		if failure >= 2 {
			state = "degraded"
		}
	case "unknown", "unsupported":
		state = "unknown"
		success, failure = 0, 0
	case "hold":
		success, failure = 0, 0
	}
	metrics, err = json.Marshal(recordedMeasurements{Measurements: result.Measurements, State: observationState{Version: 1, State: state, FreshUntil: now.UnixMilli() + int64(max(3*m.IntervalSeconds, 2*m.TimeoutSeconds))*1000}})
	if err != nil || len(metrics) > 8192 {
		return ErrInvalid
	}
	observation := newID()
	if _, err := tx.Exec(`INSERT INTO observations(id,monitor_id,monitor_revision,outcome,reason_code,measurements,observed_at,duration_ms) VALUES(?,?,?,?,?,?,?,?)`, observation, m.ID, m.Revision, result.Outcome, result.ReasonCode, string(metrics), now.UnixMilli(), result.DurationMS); err != nil {
		return err
	}
	if _, err := tx.Exec(`UPDATE monitor_states SET revision=revision+1,current_state=?,success_streak=?,failure_streak=?,last_observation_id=?,last_success_at=?,updated_at=? WHERE monitor_id=?`, state, min(success, 3), min(failure, 4), observation, lastSuccess, now.UnixMilli(), m.ID); err != nil {
		return err
	}
	// Stable per-monitor jitter avoids synchronized restarts without drifting civil time.
	jitter := int64(m.ID[0]) % int64(max(1, m.IntervalSeconds/10))
	if _, err := tx.Exec(`UPDATE monitors SET lease_token='',lease_until=0,next_at=? WHERE id=?`, now.Add(max(time.Duration(int64(m.IntervalSeconds)+jitter)*time.Second, result.RetryAfter)).UnixMilli(), m.ID); err != nil {
		return err
	}
	if err := aggregateInterval(tx, m, updated, now.UnixMilli(), intervalState); err != nil {
		return err
	}
	if err := reconcileIncident(tx, m.ComponentID, now); err != nil {
		return err
	}
	return tx.Commit()
}
func aggregateInterval(tx *sql.Tx, m Monitor, previous, now int64, state string) error {
	if previous <= 0 || previous >= now {
		return nil
	}
	from := max(previous, now-90*86400000)
	freshUntil := previous + int64(max(3*m.IntervalSeconds, 2*m.TimeoutSeconds))*1000
	maintenance := []timeWindow{}
	rows, err := tx.Query(`SELECT starts_at,ends_at FROM maintenance_windows WHERE component_id=? AND starts_at<? AND ends_at>? ORDER BY starts_at LIMIT 1001`, m.ComponentID, now, from)
	if err != nil {
		return err
	}
	for rows.Next() {
		var w timeWindow
		if rows.Scan(&w.start, &w.end) != nil {
			rows.Close()
			return ErrInvalid
		}
		maintenance = append(maintenance, w)
		if len(maintenance) > 1000 {
			rows.Close()
			return ErrInvalid
		}
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return err
	}
	controls, err := readHistoryControls(tx, m.ComponentID, []historyMonitor{{id: m.ID}}, now)
	if err != nil {
		return err
	}
	windows, resets := windowsAndResets(controls, maintenance, m.ID, now)
	for from < now {
		hour := time.UnixMilli(from).UTC().Truncate(time.Hour).UnixMilli()
		end := min(now, hour+3600000)
		totals := countTimeline(from, end, []stateEvidence{{previous, freshUntil, state}}, windows, resets)
		if _, err := tx.Exec(`INSERT INTO hourly_aggregates(monitor_id,hour_at,operational_ms,outage_ms,degraded_ms,unknown_ms,excluded_ms) VALUES(?,?,?,?,?,?,?) ON CONFLICT(monitor_id,hour_at) DO UPDATE SET operational_ms=operational_ms+excluded.operational_ms,outage_ms=outage_ms+excluded.outage_ms,degraded_ms=degraded_ms+excluded.degraded_ms,unknown_ms=unknown_ms+excluded.unknown_ms,excluded_ms=excluded_ms+excluded.excluded_ms`, m.ID, hour, totals.OperationalMS, totals.OutageMS, totals.DegradedMS, totals.UnknownMS, totals.ExcludedMS); err != nil {
			return err
		}
		from = end
	}
	return nil
}

// closeEvidence advances each affected cursor after recording its elapsed
// interval. Configuration changes cannot erase or count that interval twice.
func closeEvidence(tx *sql.Tx, where string, args []any, now int64) error {
	rows, err := tx.Query(`SELECT m.id,m.component_id,m.interval_seconds,m.timeout_seconds,s.current_state,s.updated_at FROM monitors m JOIN monitor_states s ON s.monitor_id=m.id WHERE `+where, args...)
	if err != nil {
		return err
	}
	type pending struct {
		monitor Monitor
		state   string
		updated int64
	}
	all := []pending{}
	for rows.Next() {
		var p pending
		if rows.Scan(&p.monitor.ID, &p.monitor.ComponentID, &p.monitor.IntervalSeconds, &p.monitor.TimeoutSeconds, &p.state, &p.updated) != nil {
			rows.Close()
			return ErrInvalid
		}
		all = append(all, p)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return err
	}
	for _, p := range all {
		if now < p.updated {
			return ErrConflict
		}
		if err := aggregateInterval(tx, p.monitor, p.updated, now, p.state); err != nil {
			return err
		}
		if _, err := tx.Exec(`UPDATE monitor_states SET updated_at=? WHERE monitor_id=?`, now, p.monitor.ID); err != nil {
			return err
		}
	}
	return nil
}
func reconcileIncident(tx *sql.Tx, component string, now time.Time) error {
	var maintenance int
	if err := tx.QueryRow(`SELECT COUNT(*) FROM maintenance_windows WHERE component_id=? AND starts_at<=? AND ends_at>?`, component, now.UnixMilli(), now.UnixMilli()).Scan(&maintenance); err != nil {
		return err
	}
	if maintenance > 0 {
		return nil
	}
	rows, err := tx.Query(`SELECT COALESCE(s.current_state,'unknown'),COALESCE(s.updated_at,0),m.interval_seconds,m.timeout_seconds FROM monitors m LEFT JOIN monitor_states s ON s.monitor_id=m.id WHERE m.component_id=? AND m.enabled=1`, component)
	if err != nil {
		return err
	}
	views := []MonitorView{}
	for rows.Next() {
		var state string
		var updated int64
		var interval, timeout int
		if rows.Scan(&state, &updated, &interval, &timeout) != nil {
			rows.Close()
			return ErrInvalid
		}
		if now.UnixMilli()-updated > int64(max(3*interval, 2*timeout))*1000 {
			state = "unknown"
		}
		views = append(views, MonitorView{State: state})
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return err
	}
	state := reduceComponent(views)
	var incident, prior string
	var revision int64
	err = tx.QueryRow(`SELECT id,state,revision FROM incidents WHERE component_id=? AND resolved_at=0 ORDER BY opened_at,id LIMIT 1`, component).Scan(&incident, &prior, &revision)
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return err
	}
	kind := ""
	summary := ""
	resolved := int64(0)
	if incident == "" && (state == "outage" || state == "degraded") {
		incident = newID()
		kind = "opened"
		summary = "Component requires attention"
		if _, err := tx.Exec(`INSERT INTO incidents(id,component_id,state,safe_summary,private_detail,opened_at,revision) VALUES(?,?,?,?,?,?,1)`, incident, component, state, summary, "", now.UnixMilli()); err != nil {
			return err
		}
	} else if incident != "" && state == "operational" {
		kind = "resolved"
		summary = "Component recovered"
		resolved = now.UnixMilli()
	} else if incident != "" && (state == "outage" || state == "degraded") && state != prior {
		kind = "updated"
		summary = "Component status changed"
	} else {
		return nil
	}
	if kind != "opened" {
		if _, err := tx.Exec(`UPDATE incidents SET state=?,safe_summary=?,resolved_at=?,revision=revision+1 WHERE id=?`, state, summary, resolved, incident); err != nil {
			return err
		}
	}
	var sequence int
	if err := tx.QueryRow(`SELECT COALESCE(MAX(sequence),0)+1 FROM incident_transitions WHERE incident_id=?`, incident).Scan(&sequence); err != nil {
		return err
	}
	transition := newID()
	if _, err := tx.Exec(`INSERT INTO incident_transitions(id,incident_id,sequence,kind,safe_message,occurred_at) VALUES(?,?,?,?,?,?)`, transition, incident, sequence, kind, summary, now.UnixMilli()); err != nil {
		return err
	}
	var publisherRevision int64
	err = tx.QueryRow(`SELECT revision FROM notification_publishers WHERE component_id=? AND enabled=1`, component).Scan(&publisherRevision)
	if errors.Is(err, sql.ErrNoRows) {
		return nil
	}
	if err != nil {
		return err
	}
	var notices int
	if err := tx.QueryRow(`SELECT COUNT(*) FROM notification_outbox WHERE component_id=? AND created_at>?`, component, now.Add(-time.Hour).UnixMilli()).Scan(&notices); err != nil {
		return err
	}
	if notices >= 5 {
		_, err := tx.Exec(`INSERT INTO audit_events(id,actor,action,target_id,safe_detail,created_at) VALUES(?,?,'notice.suppressed',?,'{}',?)`, newID(), "scheduler", component, now.UnixMilli())
		return err
	}
	severity := "warning"
	if state == "outage" {
		severity = "error"
	}
	if kind == "resolved" {
		severity = "resolved"
	}
	occurrence := "status:" + component + ":" + incident + ":" + strconv.Itoa(sequence)
	payload, _ := json.Marshal(map[string]string{"occurrence_id": occurrence, "title": "Service status changed", "message": "Component " + component + ": " + state, "severity": severity})
	_, err = tx.Exec(`INSERT INTO notification_outbox(id,transition_id,component_id,occurrence_id,payload,publisher_revision,state,next_at,created_at,updated_at) VALUES(?,?,?,?,?,?,'pending',?,?,?)`, newID(), transition, component, occurrence, string(payload), publisherRevision, now.UnixMilli(), now.UnixMilli(), now.UnixMilli())
	return err
}

// Run starts four bounded workers and holds the store's offline restore gate.
// Stopping the browser has no effect on this process-owned scheduler.
func (s *Store) Run(ctx context.Context, prober *Prober) error {
	s.maintenance.Lock()
	if s.running {
		s.maintenance.Unlock()
		return ErrConflict
	}
	s.running = true
	s.maintenance.Unlock()
	defer func() { s.maintenance.Lock(); s.running = false; s.maintenance.Unlock() }()
	var workers sync.WaitGroup
	for range 4 {
		workers.Add(1)
		go func() {
			defer workers.Done()
			ticker := time.NewTicker(time.Second)
			defer ticker.Stop()
			for {
				select {
				case <-ctx.Done():
					return
				case now := <-ticker.C:
					m, ok, err := s.ClaimDue(now)
					if err != nil || !ok {
						continue
					}
					func() {
						defer func() {
							if recover() != nil {
								_ = s.Record(m, unknown("invalid_response"), time.Now())
							}
						}()
						timeout, cancel := context.WithTimeout(ctx, time.Duration(m.TimeoutSeconds)*time.Second)
						defer cancel()
						result := Result{}
						if m.Kind == "heartbeat" {
							result = s.HeartbeatResult(m, time.Now())
						} else {
							result = prober.Check(timeout, m)
						}
						if ctx.Err() == nil {
							_ = s.Record(m, result, time.Now())
						}
					}()
				}
			}
		}()
	}
	<-ctx.Done()
	workers.Wait()
	return nil
}
