package status

import (
	"database/sql"
	"strings"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

// componentFilter is applied before pagination, counts and aggregate queries.
// Alias is selected only by internal callers, never from a request.
func componentFilter(v protocol.Viewer, alias string, public bool) (string, []any) {
	if public {
		return alias + `.public_enabled=1 AND ` + alias + `.enabled=1`, nil
	}
	if isAdmin(v) {
		return `1=1`, nil
	}
	if v.Subject == "" {
		return `1=0`, nil
	}
	principals := []any{"user:" + v.Subject}
	for _, ou := range v.OUs {
		principals = append(principals, "ou:"+ou)
	}
	marks := strings.TrimSuffix(strings.Repeat("?,", len(principals)), ",")
	return `EXISTS(SELECT 1 FROM component_grants g WHERE g.component_id=` + alias + `.id AND g.permission='read' AND g.principal IN (` + marks + `))`, principals
}

type IncidentView struct {
	ID            string           `json:"id"`
	ComponentID   string           `json:"component_id"`
	State         string           `json:"state"`
	Summary       string           `json:"summary"`
	OpenedAt      string           `json:"opened_at"`
	ResolvedAt    string           `json:"resolved_at"`
	Revision      int64            `json:"revision,omitempty"`
	PrivateDetail string           `json:"private_detail,omitempty"`
	Transitions   []TransitionView `json:"transitions,omitempty"`
}
type TransitionView struct {
	Sequence   int    `json:"sequence"`
	Kind       string `json:"kind"`
	Message    string `json:"message"`
	OccurredAt string `json:"occurred_at"`
}
type IncidentPage struct {
	Items  []IncidentView `json:"items"`
	Total  int            `json:"total"`
	Offset int            `json:"offset"`
	Limit  int            `json:"limit"`
}

func (s *Store) Incidents(v protocol.Viewer, public bool, offset, limit int) (IncidentPage, error) {
	page := IncidentPage{Items: []IncidentView{}, Offset: offset, Limit: limit}
	if offset < 0 || offset > 1000000 || limit < 1 || limit > 100 {
		return page, ErrInvalid
	}
	if public && s.setting("public_enabled") != "1" {
		return page, nil
	}
	filter, args := componentFilter(v, "c", public)
	if public {
		filter += ` AND i.public_enabled=1 AND i.public_summary<>''`
	}
	if err := s.db.QueryRow(`SELECT COUNT(*) FROM incidents i JOIN components c ON c.id=i.component_id WHERE `+filter, args...).Scan(&page.Total); err != nil {
		return page, err
	}
	summary := `i.safe_summary`
	if public {
		summary = `i.public_summary`
	}
	query := `SELECT i.id,i.component_id,i.state,` + summary + `,i.opened_at,i.resolved_at FROM incidents i JOIN components c ON c.id=i.component_id WHERE ` + filter + ` ORDER BY i.opened_at DESC,i.id LIMIT ? OFFSET ?`
	args = append(args, limit, offset)
	rows, err := s.db.Query(query, args...)
	if err != nil {
		return page, err
	}
	defer rows.Close()
	for rows.Next() {
		var view IncidentView
		var opened, resolved int64
		if rows.Scan(&view.ID, &view.ComponentID, &view.State, &view.Summary, &opened, &resolved) != nil {
			return page, ErrInvalid
		}
		view.OpenedAt, view.ResolvedAt = utc(opened), utc(resolved)
		page.Items = append(page.Items, view)
	}
	return page, rows.Err()
}
func (s *Store) Incident(v protocol.Viewer, id string, public bool) (IncidentView, error) {
	var view IncidentView
	if public && s.setting("public_enabled") != "1" {
		return view, ErrNotFound
	}
	filter, args := componentFilter(v, "c", public)
	if public {
		filter += ` AND i.public_enabled=1 AND i.public_summary<>''`
	}
	summary, detail, revision := `i.safe_summary`, `''`, `0`
	if public {
		summary = `i.public_summary`
	} else if isAdmin(v) {
		detail = `i.private_detail`
		revision = `i.revision`
	}
	args = append(args, id)
	var opened, resolved int64
	err := s.db.QueryRow(`SELECT i.id,i.component_id,i.state,`+summary+`,`+detail+`,`+revision+`,i.opened_at,i.resolved_at FROM incidents i JOIN components c ON c.id=i.component_id WHERE `+filter+` AND i.id=?`, args...).Scan(&view.ID, &view.ComponentID, &view.State, &view.Summary, &view.PrivateDetail, &view.Revision, &opened, &resolved)
	if err == sql.ErrNoRows {
		return view, ErrNotFound
	}
	if err != nil {
		return view, err
	}
	view.OpenedAt, view.ResolvedAt = utc(opened), utc(resolved)
	// Public transitions do not inherit private safe messages. Only the separately
	// approved narrative is public, independent of the internal incident history.
	if !public {
		rows, err := s.db.Query(`SELECT sequence,kind,safe_message,occurred_at FROM incident_transitions WHERE incident_id=? ORDER BY sequence LIMIT 100`, id)
		if err != nil {
			return view, err
		}
		defer rows.Close()
		view.Transitions = []TransitionView{}
		for rows.Next() {
			var tr TransitionView
			var at int64
			if rows.Scan(&tr.Sequence, &tr.Kind, &tr.Message, &at) != nil {
				return view, ErrInvalid
			}
			tr.OccurredAt = utc(at)
			view.Transitions = append(view.Transitions, tr)
		}
		if err := rows.Err(); err != nil {
			return view, err
		}
	}
	return view, nil
}

type Uptime struct {
	MonitorID     string `json:"monitor_id"`
	OperationalMS int64  `json:"operational_ms"`
	OutageMS      int64  `json:"outage_ms"`
	DegradedMS    int64  `json:"degraded_ms"`
	UnknownMS     int64  `json:"unknown_ms"`
	ExcludedMS    int64  `json:"excluded_ms"`
	EligibleMS    int64  `json:"eligible_ms"`
	CoverageMS    int64  `json:"coverage_ms"`
	Version       int    `json:"denominator_version"`
}

func (s *Store) History(v protocol.Viewer, component string, from, to time.Time) ([]Uptime, error) {
	if !s.canRead(v, component, "read") {
		return nil, ErrNotFound
	}
	if !from.Before(to) || to.Sub(from) > 90*24*time.Hour || to.After(time.Now().Add(24*time.Hour)) {
		return nil, ErrInvalid
	}
	// Whole buckets are explicit; unobserved partial hours are not extrapolated.
	start := from.UTC().Truncate(time.Hour)
	if start.Before(from) {
		start = start.Add(time.Hour)
	}
	end := to.UTC().Truncate(time.Hour)
	rows, err := s.db.Query(`SELECT a.monitor_id,SUM(a.operational_ms),SUM(a.outage_ms),SUM(a.degraded_ms),SUM(a.unknown_ms),SUM(a.excluded_ms) FROM hourly_aggregates a JOIN monitors m ON m.id=a.monitor_id WHERE m.component_id=? AND a.hour_at>=? AND a.hour_at<? GROUP BY a.monitor_id ORDER BY a.monitor_id LIMIT 32`, component, start.UnixMilli(), end.UnixMilli())
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []Uptime{}
	for rows.Next() {
		var h Uptime
		if rows.Scan(&h.MonitorID, &h.OperationalMS, &h.OutageMS, &h.DegradedMS, &h.UnknownMS, &h.ExcludedMS) != nil {
			return nil, ErrInvalid
		}
		h.EligibleMS = h.OperationalMS + h.OutageMS + h.DegradedMS
		h.CoverageMS = h.EligibleMS + h.UnknownMS
		h.Version = 1
		out = append(out, h)
	}
	return out, rows.Err()
}

type MaintenanceInput struct {
	ComponentID string `json:"component_id"`
	StartsAt    string `json:"starts_at"`
	EndsAt      string `json:"ends_at"`
	Summary     string `json:"summary"`
}

func (s *Store) SaveMaintenance(v protocol.Viewer, in MaintenanceInput) error {
	if !isAdmin(v) {
		return ErrForbidden
	}
	start, err := time.Parse(time.RFC3339, in.StartsAt)
	if err != nil {
		return ErrInvalid
	}
	end, err := time.Parse(time.RFC3339, in.EndsAt)
	if err != nil || !end.After(start) || end.Sub(start) > 90*24*time.Hour || len(in.Summary) > 500 {
		return ErrInvalid
	}
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	id := newID()
	now := time.Now().UnixMilli()
	if _, err := tx.Exec(`INSERT INTO maintenance_windows(id,component_id,starts_at,ends_at,safe_summary,created_by,created_at) VALUES(?,?,?,?,?,?,?)`, id, in.ComponentID, start.UnixMilli(), end.UnixMilli(), in.Summary, v.Subject, now); err != nil {
		return ErrInvalid
	}
	// Previously healthy evidence cannot survive a newly scheduled maintenance
	// boundary as a fresh post-maintenance result.
	if _, err := tx.Exec(`UPDATE monitor_states SET current_state='unknown',success_streak=0,failure_streak=0 WHERE monitor_id IN(SELECT id FROM monitors WHERE component_id=?)`, in.ComponentID); err != nil {
		return err
	}
	if err := audit(tx, v, "maintenance.create", id, now); err != nil {
		return err
	}
	return tx.Commit()
}
func (s *Store) PublishIncident(v protocol.Viewer, id string, revision int64, summary string, enabled bool) error {
	if !isAdmin(v) {
		return ErrForbidden
	}
	if len(summary) > 1000 || (enabled && strings.TrimSpace(summary) == "") {
		return ErrInvalid
	}
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	result, err := tx.Exec(`UPDATE incidents SET public_summary=?,public_enabled=?,revision=revision+1 WHERE id=? AND revision=?`, summary, enabled, id, revision)
	if err != nil {
		return err
	}
	n, _ := result.RowsAffected()
	if n != 1 {
		return ErrConflict
	}
	if err := audit(tx, v, "incident.publish", id, time.Now().UnixMilli()); err != nil {
		return err
	}
	return tx.Commit()
}
