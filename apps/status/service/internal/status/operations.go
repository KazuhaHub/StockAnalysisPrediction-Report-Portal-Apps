package status

import (
	"encoding/json"
	"net/netip"
	"net/url"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

type ServiceSettings struct {
	PublicEnabled  bool           `json:"public_enabled"`
	ProbesPaused   bool           `json:"probes_paused"`
	OutboxPaused   bool           `json:"outbox_paused"`
	PortalURL      string         `json:"portal_url"`
	PortalNetworks []netip.Prefix `json:"portal_networks"`
}

func (s *Store) Settings() ServiceSettings {
	out := ServiceSettings{PublicEnabled: s.setting("public_enabled") == "1", ProbesPaused: s.setting("probes_paused") == "1", OutboxPaused: s.setting("outbox_paused") == "1", PortalURL: s.setting("portal_url"), PortalNetworks: []netip.Prefix{}}
	json.Unmarshal([]byte(s.setting("portal_networks")), &out.PortalNetworks)
	return out
}
func (s *Store) SaveSettings(v protocol.Viewer, in ServiceSettings) error {
	if !isAdmin(v) {
		return ErrForbidden
	}
	if in.PortalURL != "" {
		u, err := url.Parse(in.PortalURL)
		if err != nil || u.Scheme != "https" || u.Hostname() == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || (u.Path != "" && u.Path != "/") || len(in.PortalURL) > 2048 {
			return ErrInvalid
		}
		if _, err := newProbeTransport(ProbeConfig{URL: in.PortalURL, Networks: in.PortalNetworks}); err != nil {
			return ErrInvalid
		}
	}
	if len(in.PortalNetworks) > 16 {
		return ErrInvalid
	}
	for _, prefix := range in.PortalNetworks {
		if !prefix.IsValid() {
			return ErrInvalid
		}
	}
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	// Resume always requires the separately reviewed queue fingerprint.
	var probes, outbox string
	tx.QueryRow(`SELECT value FROM settings WHERE key='probes_paused'`).Scan(&probes)
	tx.QueryRow(`SELECT value FROM settings WHERE key='outbox_paused'`).Scan(&outbox)
	if (probes == "1" && !in.ProbesPaused) || (outbox == "1" && !in.OutboxPaused) {
		return ErrConflict
	}
	var priorURL, priorNetworks string
	tx.QueryRow(`SELECT value FROM settings WHERE key='portal_url'`).Scan(&priorURL)
	tx.QueryRow(`SELECT value FROM settings WHERE key='portal_networks'`).Scan(&priorNetworks)
	networks, _ := json.Marshal(in.PortalNetworks)
	if priorURL != in.PortalURL || priorNetworks != string(networks) {
		for _, q := range []string{`UPDATE notification_publishers SET enabled=0,revision=revision+1`, `UPDATE notification_outbox SET state='review_required',lease_token='',lease_until=0,last_error='publisher_changed' WHERE state IN('pending','retry','leased')`} {
			if _, err := tx.Exec(q); err != nil {
				return err
			}
		}
	}
	values := map[string]string{"public_enabled": boolString(in.PublicEnabled), "probes_paused": boolString(in.ProbesPaused), "outbox_paused": boolString(in.OutboxPaused), "portal_url": in.PortalURL, "portal_networks": string(networks)}
	for key, value := range values {
		if err := setSetting(tx, key, value); err != nil {
			return err
		}
	}
	if in.ProbesPaused {
		now := time.Now().UnixMilli()
		if err := closeEvidence(tx, "1=1", nil, now); err != nil {
			return err
		}
		if probes != "1" {
			if err := audit(tx, v, "probes.pause", "service", now); err != nil {
				return err
			}
		}
		if _, err := tx.Exec(`UPDATE monitors SET lease_token='',lease_until=0,revision=revision+1`); err != nil {
			return err
		}
		if _, err := tx.Exec(`UPDATE monitor_states SET current_state='unknown',success_streak=0,failure_streak=0`); err != nil {
			return err
		}
	}
	if err := audit(tx, v, "service.settings", "service", time.Now().UnixMilli()); err != nil {
		return err
	}
	return tx.Commit()
}
func boolString(value bool) string {
	if value {
		return "1"
	}
	return "0"
}
func (s *Store) ReviewNotice(v protocol.Viewer, id, fingerprint, action string) error {
	if !isAdmin(v) {
		return ErrForbidden
	}
	if action != "retry_same_publisher" && action != "discard" {
		return ErrInvalid
	}
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	actual, err := queueFingerprint(tx)
	if err != nil {
		return err
	}
	if actual != fingerprint {
		return ErrConflict
	}
	state := "discarded"
	if action == "retry_same_publisher" {
		var valid int
		if err := tx.QueryRow(`SELECT COUNT(*) FROM notification_outbox o JOIN notification_publishers p ON p.component_id=o.component_id WHERE o.id=? AND o.state='review_required' AND p.enabled=1 AND p.revision=o.publisher_revision`, id).Scan(&valid); err != nil {
			return err
		}
		if valid != 1 {
			return ErrConflict
		}
		state = "retry"
	}
	result, err := tx.Exec(`UPDATE notification_outbox SET state=?,last_error='',next_at=?,lease_token='',lease_until=0,updated_at=? WHERE id=? AND state='review_required'`, state, time.Now().UnixMilli(), time.Now().UnixMilli(), id)
	if err != nil {
		return err
	}
	n, _ := result.RowsAffected()
	if n != 1 {
		return ErrConflict
	}
	if err := audit(tx, v, "notice."+action, id, time.Now().UnixMilli()); err != nil {
		return err
	}
	return tx.Commit()
}

// Cleanup uses a bounded transaction. Active incidents and unresolved outbox
// families prevent history deletion; acknowledgement/discard tombstones last as
// long as their incident family. No background purge can erase active evidence.
func (s *Store) Cleanup(now time.Time) error {
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	cutoff := now.Add(-90 * 24 * time.Hour).UnixMilli()
	queries := []struct {
		q    string
		args []any
	}{
		{`DELETE FROM hourly_aggregates WHERE rowid IN(SELECT rowid FROM hourly_aggregates WHERE hour_at<? LIMIT 500)`, []any{now.Add(-90 * 24 * time.Hour).UTC().Truncate(time.Hour).UnixMilli()}},
		{`DELETE FROM audit_events WHERE id IN(SELECT a.id FROM audit_events a WHERE a.created_at<? AND (a.action NOT IN('probes.pause','probes.resume','component.pause','component.resume','monitor.pause','monitor.resume') OR EXISTS(SELECT 1 FROM audit_events b WHERE b.target_id=a.target_id AND b.action IN('probes.pause','probes.resume','component.pause','component.resume','monitor.pause','monitor.resume') AND b.created_at<? AND (b.created_at>a.created_at OR (b.created_at=a.created_at AND b.rowid>a.rowid)))) ORDER BY a.created_at LIMIT 500)`, []any{cutoff, cutoff}},
		{`DELETE FROM notification_outbox WHERE id IN(SELECT o.id FROM notification_outbox o JOIN incidents i ON i.id=(SELECT incident_id FROM incident_transitions WHERE id=o.transition_id) WHERE i.resolved_at>0 AND i.resolved_at<? AND o.state IN('delivered','discarded') LIMIT 100)`, []any{cutoff}},
		{`DELETE FROM incidents WHERE id IN(SELECT i.id FROM incidents i WHERE i.resolved_at>0 AND i.resolved_at<? AND NOT EXISTS(SELECT 1 FROM incident_transitions t JOIN notification_outbox o ON o.transition_id=t.id WHERE t.incident_id=i.id) LIMIT 100)`, []any{cutoff}},
		{`DELETE FROM observations WHERE id IN(SELECT o.id FROM observations o JOIN monitors m ON m.id=o.monitor_id WHERE o.observed_at<? AND NOT EXISTS(SELECT 1 FROM incidents i WHERE i.component_id=m.component_id AND i.resolved_at=0) AND NOT EXISTS(SELECT 1 FROM notification_outbox n WHERE n.component_id=m.component_id AND n.state NOT IN('delivered','discarded')) ORDER BY o.observed_at LIMIT 500)`, []any{now.Add(-30 * 24 * time.Hour).UnixMilli()}},
	}
	for _, query := range queries {
		if _, err := tx.Exec(query.q, query.args...); err != nil {
			return err
		}
	}
	return tx.Commit()
}
func (s *Store) OutboxViews() ([]map[string]any, error) {
	rows, err := s.db.Query(`SELECT id,component_id,occurrence_id,state,attempts,next_at,last_error,portal_event_id FROM notification_outbox ORDER BY created_at DESC,id LIMIT 100`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []map[string]any{}
	for rows.Next() {
		var id, component, occurrence, state, last, event string
		var attempts int
		var next int64
		if rows.Scan(&id, &component, &occurrence, &state, &attempts, &next, &last, &event) != nil {
			return nil, ErrInvalid
		}
		out = append(out, map[string]any{"id": id, "component_id": component, "occurrence_id": occurrence, "state": state, "attempts": attempts, "next_at": utc(next), "last_error": last, "portal_event_id": event})
	}
	return out, rows.Err()
}
func (s *Store) PublisherViews() ([]PublisherInput, error) {
	rows, err := s.db.Query(`SELECT component_id,publisher_name,credential_id,enabled,revision FROM notification_publishers ORDER BY component_id LIMIT 100`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []PublisherInput{}
	for rows.Next() {
		var p PublisherInput
		if rows.Scan(&p.ComponentID, &p.PublisherName, &p.CredentialID, &p.Enabled, &p.Revision) != nil {
			return nil, ErrInvalid
		}
		out = append(out, p)
	}
	return out, rows.Err()
}
func parseRange(from, to string) (time.Time, time.Time, error) {
	until := time.Now().UTC()
	since := until.Add(-7 * 24 * time.Hour)
	var err error
	if to != "" {
		until, err = time.Parse(time.RFC3339, to)
		if err != nil {
			return since, until, ErrInvalid
		}
	}
	if from != "" {
		since, err = time.Parse(time.RFC3339, from)
		if err != nil {
			return since, until, ErrInvalid
		}
	}
	if !since.Before(until) || until.Sub(since) > 90*24*time.Hour {
		return since, until, ErrInvalid
	}
	return since, until, nil
}

// Registered infrastructure settings contain destinations, not authentication.
// Provider secrets are stored only in credentials with authenticated encryption.
