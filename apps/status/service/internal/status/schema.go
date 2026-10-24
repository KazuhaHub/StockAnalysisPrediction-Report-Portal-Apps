package status

import (
	"database/sql"
	"errors"
	"fmt"
	"strings"
	"time"
)

type schemaProduct struct{ name, columns, ddl string }

var products = []schemaProduct{
	{"schema_migrations", "version,applied_at", `version INTEGER PRIMARY KEY,applied_at BIGINT NOT NULL`},
	{"settings", "key,value", `key TEXT PRIMARY KEY,value TEXT NOT NULL`},
	{"credentials", "id,kind,label,sealed_value,revision,created_at,updated_at", `id TEXT PRIMARY KEY,kind TEXT NOT NULL,label TEXT NOT NULL,sealed_value TEXT NOT NULL,revision BIGINT NOT NULL,created_at BIGINT NOT NULL,updated_at BIGINT NOT NULL`},
	{"components", "id,label,public_label,public_enabled,enabled,revision,created_at,updated_at", `id TEXT PRIMARY KEY,label TEXT NOT NULL,public_label TEXT NOT NULL DEFAULT '',public_enabled INTEGER NOT NULL DEFAULT 0 CHECK(public_enabled IN(0,1)),enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN(0,1)),revision BIGINT NOT NULL,created_at BIGINT NOT NULL,updated_at BIGINT NOT NULL`},
	{"component_grants", "component_id,principal,permission", `component_id TEXT NOT NULL REFERENCES components(id) ON DELETE CASCADE,principal TEXT NOT NULL,permission TEXT NOT NULL CHECK(permission IN('read','finance')),PRIMARY KEY(component_id,principal,permission)`},
	{"monitors", "id,component_id,kind,label,credential_id,config,enabled,interval_seconds,timeout_seconds,revision,next_at,lease_token,lease_until,created_at,updated_at", `id TEXT PRIMARY KEY,component_id TEXT NOT NULL REFERENCES components(id) ON DELETE RESTRICT,kind TEXT NOT NULL,label TEXT NOT NULL,credential_id TEXT REFERENCES credentials(id) ON DELETE RESTRICT,config TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN(0,1)),interval_seconds INTEGER NOT NULL,timeout_seconds INTEGER NOT NULL,revision BIGINT NOT NULL,next_at BIGINT NOT NULL,lease_token TEXT NOT NULL DEFAULT '',lease_until BIGINT NOT NULL DEFAULT 0,created_at BIGINT NOT NULL,updated_at BIGINT NOT NULL`},
	{"observations", "id,monitor_id,monitor_revision,outcome,reason_code,measurements,observed_at,duration_ms", `id TEXT PRIMARY KEY,monitor_id TEXT NOT NULL REFERENCES monitors(id) ON DELETE RESTRICT,monitor_revision BIGINT NOT NULL,outcome TEXT NOT NULL,reason_code TEXT NOT NULL,measurements TEXT NOT NULL,observed_at BIGINT NOT NULL,duration_ms BIGINT NOT NULL`},
	{"monitor_states", "monitor_id,revision,current_state,success_streak,failure_streak,last_observation_id,last_success_at,updated_at", `monitor_id TEXT PRIMARY KEY REFERENCES monitors(id) ON DELETE RESTRICT,revision BIGINT NOT NULL,current_state TEXT NOT NULL,success_streak INTEGER NOT NULL,failure_streak INTEGER NOT NULL,last_observation_id TEXT REFERENCES observations(id) ON DELETE SET NULL,last_success_at BIGINT NOT NULL DEFAULT 0,updated_at BIGINT NOT NULL`},
	{"incidents", "id,component_id,state,safe_summary,private_detail,public_summary,public_enabled,opened_at,resolved_at,revision", `id TEXT PRIMARY KEY,component_id TEXT NOT NULL REFERENCES components(id) ON DELETE RESTRICT,state TEXT NOT NULL,safe_summary TEXT NOT NULL,private_detail TEXT NOT NULL,public_summary TEXT NOT NULL DEFAULT '',public_enabled INTEGER NOT NULL DEFAULT 0 CHECK(public_enabled IN(0,1)),opened_at BIGINT NOT NULL,resolved_at BIGINT NOT NULL DEFAULT 0,revision BIGINT NOT NULL`},
	{"incident_transitions", "id,incident_id,sequence,kind,safe_message,occurred_at", `id TEXT PRIMARY KEY,incident_id TEXT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,sequence INTEGER NOT NULL,kind TEXT NOT NULL,safe_message TEXT NOT NULL,occurred_at BIGINT NOT NULL,UNIQUE(incident_id,sequence)`},
	{"maintenance_windows", "id,component_id,starts_at,ends_at,safe_summary,created_by,created_at", `id TEXT PRIMARY KEY,component_id TEXT NOT NULL REFERENCES components(id) ON DELETE CASCADE,starts_at BIGINT NOT NULL,ends_at BIGINT NOT NULL CHECK(ends_at>starts_at),safe_summary TEXT NOT NULL,created_by TEXT NOT NULL,created_at BIGINT NOT NULL`},
	{"hourly_aggregates", "monitor_id,hour_at,operational_ms,outage_ms,degraded_ms,unknown_ms,excluded_ms", `monitor_id TEXT NOT NULL REFERENCES monitors(id) ON DELETE CASCADE,hour_at BIGINT NOT NULL,operational_ms BIGINT NOT NULL,outage_ms BIGINT NOT NULL,degraded_ms BIGINT NOT NULL,unknown_ms BIGINT NOT NULL,excluded_ms BIGINT NOT NULL,PRIMARY KEY(monitor_id,hour_at)`},
	{"notification_publishers", "component_id,publisher_name,credential_id,enabled,revision,updated_at", `component_id TEXT PRIMARY KEY REFERENCES components(id) ON DELETE RESTRICT,publisher_name TEXT NOT NULL UNIQUE,credential_id TEXT NOT NULL REFERENCES credentials(id) ON DELETE RESTRICT,enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN(0,1)),revision BIGINT NOT NULL,updated_at BIGINT NOT NULL`},
	{"notification_outbox", "id,transition_id,component_id,occurrence_id,payload,publisher_revision,state,attempts,next_at,lease_token,lease_until,last_error,portal_event_id,created_at,updated_at", `id TEXT PRIMARY KEY,transition_id TEXT NOT NULL UNIQUE REFERENCES incident_transitions(id) ON DELETE RESTRICT,component_id TEXT NOT NULL REFERENCES components(id) ON DELETE RESTRICT,occurrence_id TEXT NOT NULL UNIQUE,payload TEXT NOT NULL,publisher_revision BIGINT NOT NULL,state TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,next_at BIGINT NOT NULL,lease_token TEXT NOT NULL DEFAULT '',lease_until BIGINT NOT NULL DEFAULT 0,last_error TEXT NOT NULL DEFAULT '',portal_event_id TEXT NOT NULL DEFAULT '',created_at BIGINT NOT NULL,updated_at BIGINT NOT NULL`},
	{"audit_events", "id,actor,action,target_id,safe_detail,created_at", `id TEXT PRIMARY KEY,actor TEXT NOT NULL,action TEXT NOT NULL,target_id TEXT NOT NULL,safe_detail TEXT NOT NULL,created_at BIGINT NOT NULL`},
}
var indexes = map[string]string{
	"idx_monitors_due":         "monitors(enabled,next_at,lease_until)",
	"idx_observations_time":    "observations(monitor_id,observed_at,id)",
	"idx_incidents_time":       "incidents(component_id,opened_at,id)",
	"idx_transitions_sequence": "incident_transitions(incident_id,sequence)",
	"idx_maintenance_time":     "maintenance_windows(component_id,starts_at,ends_at)",
	"idx_outbox_due":           "notification_outbox(state,next_at,lease_until)",
	"idx_audit_time":           "audit_events(created_at,id)",
}

func (s *Store) migrate() error {
	var tables int
	if err := s.db.QueryRow(`SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'`).Scan(&tables); err != nil {
		return err
	}
	if tables > 0 {
		return s.verify()
	}
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	for _, p := range products {
		if _, err := tx.Exec(`CREATE TABLE ` + p.name + ` (` + p.ddl + `)`); err != nil {
			return err
		}
	}
	for name, target := range indexes {
		if _, err := tx.Exec(`CREATE INDEX ` + name + ` ON ` + target); err != nil {
			return err
		}
	}
	for _, key := range []string{"probes_paused", "outbox_paused"} {
		if err := setSetting(tx, key, "1"); err != nil {
			return err
		}
	}
	if _, err := tx.Exec(`INSERT INTO audit_events(id,actor,action,target_id,safe_detail,created_at) VALUES(?,'bootstrap','probes.pause','service','{}',?)`, newID(), time.Now().UnixMilli()); err != nil {
		return err
	}
	if _, err := tx.Exec(`INSERT INTO schema_migrations(version,applied_at) VALUES(1,?)`, time.Now().UnixMilli()); err != nil {
		return err
	}
	return tx.Commit()
}
func (s *Store) verify() error {
	var version, count int
	if err := s.db.QueryRow(`SELECT COALESCE(MAX(version),0),COUNT(*) FROM schema_migrations`).Scan(&version, &count); err != nil {
		return errors.New("status schema is incomplete")
	}
	if version != 1 || count != 1 {
		return errors.New("unsupported status schema version")
	}
	for _, p := range products {
		rows, err := s.db.Query(`SELECT ` + p.columns + ` FROM ` + p.name + ` LIMIT 0`)
		if err != nil {
			return fmt.Errorf("status schema product missing: %s", p.name)
		}
		rows.Close()
	}
	for name := range indexes {
		var n int
		if err := s.db.QueryRow(`SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name=?`, name).Scan(&n); err != nil || n != 1 {
			return fmt.Errorf("status schema index missing: %s", name)
		}
	}
	var integrity string
	if err := s.db.QueryRow(`PRAGMA quick_check`).Scan(&integrity); err != nil || integrity != "ok" {
		return errors.New("status database integrity check failed")
	}
	rows, err := s.db.Query(`PRAGMA foreign_key_check`)
	if err != nil {
		return err
	}
	defer rows.Close()
	if rows.Next() {
		return errors.New("status database has broken references")
	}
	return rows.Err()
}
func (s *Store) setting(key string) string {
	var value string
	s.db.QueryRow(`SELECT value FROM settings WHERE key=?`, key).Scan(&value)
	return value
}
func setSetting(tx *sql.Tx, key, value string) error {
	if !strings.Contains("|probes_paused|outbox_paused|public_enabled|storage_key_fingerprint|portal_url|portal_networks|raw_retention_days|history_retention_days|", "|"+key+"|") {
		return errors.New("unregistered status setting")
	}
	_, err := tx.Exec(`INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value`, key, value)
	return err
}
