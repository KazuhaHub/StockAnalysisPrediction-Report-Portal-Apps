package status

import (
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/netip"
	"net/url"
	"strings"
	"time"
	"unicode/utf8"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

var (
	ErrForbidden = errors.New("status access denied")
	ErrConflict  = errors.New("status record changed; reload before saving")
	ErrInvalid   = errors.New("invalid status configuration")
	ErrNotFound  = errors.New("status record not found")
)

func newID() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		panic("random source unavailable")
	}
	return hex.EncodeToString(b[:])
}
func utc(ms int64) string {
	if ms == 0 {
		return ""
	}
	return time.UnixMilli(ms).UTC().Format(time.RFC3339Nano)
}
func isAdmin(v protocol.Viewer) bool { return v.Subject != "" && v.Role == "admin" }
func audit(tx *sql.Tx, v protocol.Viewer, action, target string, now int64) error {
	_, err := tx.Exec(`INSERT INTO audit_events(id,actor,action,target_id,safe_detail,created_at) VALUES(?,?,?,?,?,?)`, newID(), v.Subject, action, target, "{}", now)
	return err
}

type Grant struct {
	Principal  string `json:"principal"`
	Permission string `json:"permission"`
}
type ComponentInput struct {
	ID            string         `json:"id,omitempty"`
	Revision      int64          `json:"revision"`
	Label         string         `json:"label"`
	PublicLabel   string         `json:"public_label"`
	PublicEnabled bool           `json:"public_enabled"`
	Enabled       bool           `json:"enabled"`
	Grants        []Grant        `json:"grants"`
	Monitors      []MonitorInput `json:"monitors"`
}
type MonitorInput struct {
	Revision        int64           `json:"revision,omitempty"`
	ID              string          `json:"id,omitempty"`
	Kind            string          `json:"kind"`
	Label           string          `json:"label"`
	CredentialID    string          `json:"credential_id,omitempty"`
	Config          json.RawMessage `json:"config"`
	Enabled         bool            `json:"enabled"`
	IntervalSeconds int             `json:"interval_seconds"`
	TimeoutSeconds  int             `json:"timeout_seconds"`
}
type ProbeConfig struct {
	ExpectedStatus  int            `json:"expected_status,omitempty"`
	BodyContains    string         `json:"body_contains,omitempty"`
	AccountRef      string         `json:"account_ref,omitempty"`
	Version         int            `json:"version"`
	URL             string         `json:"url,omitempty"`
	Host            string         `json:"host,omitempty"`
	Port            uint16         `json:"port,omitempty"`
	Database        string         `json:"database,omitempty"`
	Networks        []netip.Prefix `json:"networks,omitempty"`
	PlainHTTP       bool           `json:"plain_http,omitempty"`
	Site            string         `json:"site,omitempty"`
	LowBalance      string         `json:"low_balance,omitempty"`
	RecoveryBalance string         `json:"recovery_balance,omitempty"`
	Currency        string         `json:"currency,omitempty"`
}

func validateMonitor(m *MonitorInput) error {
	if m.Label == "" || len(m.Label) > 120 || len(m.Config) > 16384 {
		return ErrInvalid
	}
	if m.IntervalSeconds == 0 {
		m.IntervalSeconds = 60
	}
	if m.Kind == "deepseek" || m.Kind == "qwen" {
		if m.IntervalSeconds < 300 {
			m.IntervalSeconds = 300
		}
	}
	if m.IntervalSeconds < 30 || m.IntervalSeconds > 86400 || m.TimeoutSeconds < 1 || m.TimeoutSeconds > 15 {
		return ErrInvalid
	}
	if len(m.Config) == 0 {
		m.Config = json.RawMessage(`{}`)
	}
	var c ProbeConfig
	d := json.NewDecoder(strings.NewReader(string(m.Config)))
	d.DisallowUnknownFields()
	if d.Decode(&c) != nil {
		return ErrInvalid
	}
	if c.Version == 0 {
		c.Version = 1
	}
	if c.Version != 1 || len(c.Networks) > 16 {
		return ErrInvalid
	}
	for _, prefix := range c.Networks {
		if !prefix.IsValid() {
			return ErrInvalid
		}
	}
	if (c.ExpectedStatus != 0 && (c.ExpectedStatus < 100 || c.ExpectedStatus > 599)) || utf8.RuneCountInString(c.BodyContains) > 256 || (m.Kind != "http" && (c.ExpectedStatus != 0 || c.BodyContains != "")) {
		return ErrInvalid
	}
	switch m.Kind {
	case "http", "dify":
		u, err := url.Parse(c.URL)
		if err != nil || u.Hostname() == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || (u.Scheme != "https" && !(u.Scheme == "http" && c.PlainHTTP && len(c.Networks) > 0)) {
			return ErrInvalid
		}
		if m.Kind == "dify" && m.CredentialID == "" {
			return ErrInvalid
		}
	case "heartbeat":
		if m.CredentialID == "" || c.URL != "" || c.Host != "" || c.Site != "" || len(c.Networks) > 0 {
			return ErrInvalid
		}
	case "postgres":
		if c.Host == "" || strings.ContainsAny(c.Host, "/\\@?# ") || c.Port == 0 || c.Database == "" || m.CredentialID == "" {
			return ErrInvalid
		}
	case "deepseek", "qwen":
		if !billingReference.MatchString(c.AccountRef) {
			return ErrInvalid
		}
		if c.LowBalance != "" {
			if _, ok := decimal(c.LowBalance); !ok {
				return ErrInvalid
			}
		}
		if c.RecoveryBalance != "" {
			low, ok := decimal(c.LowBalance)
			if !ok {
				return ErrInvalid
			}
			high, ok := decimal(c.RecoveryBalance)
			if !ok || high.Cmp(low) < 0 {
				return ErrInvalid
			}
		}
		if m.CredentialID == "" || c.URL != "" || c.Host != "" || c.PlainHTTP || len(c.Networks) > 0 {
			return ErrInvalid
		}
		if m.Kind == "qwen" && c.Site != "china" && c.Site != "international" {
			return ErrInvalid
		}
		if c.Currency == "" {
			c.Currency = "CNY"
		}
		if c.Currency != "CNY" && c.Currency != "USD" {
			return ErrInvalid
		}
	default:
		return ErrInvalid
	}
	m.Config, _ = json.Marshal(c)
	return nil
}
func (s *Store) canRead(v protocol.Viewer, component, permission string) bool {
	if isAdmin(v) {
		return true
	}
	if v.Subject == "" {
		return false
	}
	principals := []string{"user:" + v.Subject}
	for _, ou := range v.OUs {
		principals = append(principals, "ou:"+ou)
	}
	marks := strings.TrimSuffix(strings.Repeat("?,", len(principals)), ",")
	args := []any{component, permission}
	for _, p := range principals {
		args = append(args, p)
	}
	var n int
	err := s.db.QueryRow(`SELECT COUNT(*) FROM component_grants WHERE component_id=? AND permission=? AND principal IN (`+marks+`)`, args...).Scan(&n)
	return err == nil && n > 0
}
func (s *Store) SaveComponent(v protocol.Viewer, in ComponentInput) (ComponentInput, error) {
	if !isAdmin(v) {
		return ComponentInput{}, ErrForbidden
	}
	if strings.TrimSpace(in.Label) == "" || len(in.Label) > 120 || len(in.PublicLabel) > 120 || len(in.Grants) > 256 || len(in.Monitors) > 32 || in.Revision < 0 || (in.PublicEnabled && strings.TrimSpace(in.PublicLabel) == "") {
		return ComponentInput{}, ErrInvalid
	}
	seen := map[string]bool{}
	for _, g := range in.Grants {
		if (!strings.HasPrefix(g.Principal, "user:") && !strings.HasPrefix(g.Principal, "ou:")) || len(g.Principal) > 300 || (g.Permission != "read" && g.Permission != "finance") || seen[g.Principal+":"+g.Permission] {
			return ComponentInput{}, ErrInvalid
		}
		seen[g.Principal+":"+g.Permission] = true
	}
	for i := range in.Monitors {
		if err := validateMonitor(&in.Monitors[i]); err != nil {
			return ComponentInput{}, err
		}
	}
	tx, err := s.db.Begin()
	if err != nil {
		return ComponentInput{}, err
	}
	defer tx.Rollback()
	if err := validateBillingIdentity(tx, in); err != nil {
		return ComponentInput{}, err
	}
	now := time.Now().UnixMilli()
	if in.ID == "" {
		if in.Revision != 0 {
			return ComponentInput{}, ErrConflict
		}
		in.ID = newID()
		_, err = tx.Exec(`INSERT INTO components(id,label,public_label,public_enabled,enabled,revision,created_at,updated_at) VALUES(?,?,?,?,?,1,?,?)`, in.ID, in.Label, in.PublicLabel, in.PublicEnabled, in.Enabled, now, now)
	} else {
		var result sql.Result
		result, err = tx.Exec(`UPDATE components SET label=?,public_label=?,public_enabled=?,enabled=?,revision=revision+1,updated_at=? WHERE id=? AND revision=?`, in.Label, in.PublicLabel, in.PublicEnabled, in.Enabled, now, in.ID, in.Revision)
		if err == nil {
			n, _ := result.RowsAffected()
			if n != 1 {
				return ComponentInput{}, ErrConflict
			}
		}
	}
	if err != nil {
		return ComponentInput{}, err
	}
	if _, err := tx.Exec(`DELETE FROM component_grants WHERE component_id=?`, in.ID); err != nil {
		return ComponentInput{}, err
	}
	for _, g := range in.Grants {
		if _, err := tx.Exec(`INSERT INTO component_grants(component_id,principal,permission) VALUES(?,?,?)`, in.ID, g.Principal, g.Permission); err != nil {
			return ComponentInput{}, err
		}
	}
	if err := closeEvidence(tx, "m.component_id=?", []any{in.ID}, now); err != nil {
		return ComponentInput{}, err
	}
	oldEnabled := map[string]bool{}
	oldRows, err := tx.Query(`SELECT id,enabled FROM monitors WHERE component_id=?`, in.ID)
	if err != nil {
		return ComponentInput{}, err
	}
	for oldRows.Next() {
		var id string
		var enabled bool
		if oldRows.Scan(&id, &enabled) != nil {
			oldRows.Close()
			return ComponentInput{}, ErrInvalid
		}
		oldEnabled[id] = enabled
	}
	err = oldRows.Err()
	oldRows.Close()
	if err != nil {
		return ComponentInput{}, err
	}
	// Omitted monitors are archived; retained observations and incident evidence stay.
	if _, err := tx.Exec(`UPDATE monitors SET enabled=0,revision=revision+1,lease_token='',lease_until=0 WHERE component_id=?`, in.ID); err != nil {
		return ComponentInput{}, err
	}
	monitorIDs := map[string]bool{}
	for i := range in.Monitors {
		m := &in.Monitors[i]
		if m.ID != "" && monitorIDs[m.ID] {
			return ComponentInput{}, ErrInvalid
		}
		monitorIDs[m.ID] = true
		if m.CredentialID != "" {
			var kind string
			if err := tx.QueryRow(`SELECT kind FROM credentials WHERE id=?`, m.CredentialID).Scan(&kind); err != nil || kind != m.Kind {
				return ComponentInput{}, ErrInvalid
			}
		}
		if m.ID == "" {
			m.ID = newID()
		} else {
			var owner string
			if tx.QueryRow(`SELECT component_id FROM monitors WHERE id=?`, m.ID).Scan(&owner) != nil || owner != in.ID {
				return ComponentInput{}, ErrConflict
			}
		}
		var credential any
		if m.CredentialID != "" {
			credential = m.CredentialID
		}
		_, err := tx.Exec(`INSERT INTO monitors(id,component_id,kind,label,credential_id,config,enabled,interval_seconds,timeout_seconds,revision,next_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,1,?,?,?) ON CONFLICT(id) DO UPDATE SET kind=excluded.kind,label=excluded.label,credential_id=excluded.credential_id,config=excluded.config,enabled=excluded.enabled,interval_seconds=excluded.interval_seconds,timeout_seconds=excluded.timeout_seconds,next_at=excluded.next_at,updated_at=excluded.updated_at`, m.ID, in.ID, m.Kind, m.Label, credential, string(m.Config), m.Enabled, m.IntervalSeconds, m.TimeoutSeconds, now, now, now)
		if err != nil {
			return ComponentInput{}, err
		}
		if _, err := tx.Exec(`INSERT INTO monitor_states(monitor_id,revision,current_state,success_streak,failure_streak,updated_at) VALUES(?,1,'unknown',0,0,?) ON CONFLICT(monitor_id) DO UPDATE SET current_state='unknown',success_streak=0,failure_streak=0,last_observation_id=NULL,last_success_at=0,revision=revision+1,updated_at=excluded.updated_at`, m.ID, now); err != nil {
			return ComponentInput{}, err
		}
	}
	finalRows, err := tx.Query(`SELECT id,enabled FROM monitors WHERE component_id=?`, in.ID)
	if err != nil {
		return ComponentInput{}, err
	}
	type change struct {
		id      string
		enabled bool
	}
	changes := []change{}
	for finalRows.Next() {
		var c change
		if finalRows.Scan(&c.id, &c.enabled) != nil {
			finalRows.Close()
			return ComponentInput{}, ErrInvalid
		}
		old, exists := oldEnabled[c.id]
		if !exists || old != c.enabled {
			changes = append(changes, c)
		}
	}
	err = finalRows.Err()
	finalRows.Close()
	if err != nil {
		return ComponentInput{}, err
	}
	for _, c := range changes {
		action := "monitor.pause"
		if c.enabled {
			action = "monitor.resume"
		}
		if err := audit(tx, v, action, c.id, now); err != nil {
			return ComponentInput{}, err
		}
	}
	componentAction := "component.pause"
	if in.Enabled {
		componentAction = "component.resume"
	}
	if err := audit(tx, v, componentAction, in.ID, now); err != nil {
		return ComponentInput{}, err
	}
	if err := audit(tx, v, "component.save", in.ID, now); err != nil {
		return ComponentInput{}, err
	}
	if err := tx.Commit(); err != nil {
		return ComponentInput{}, err
	}
	in.Revision++
	return in, nil
}

type CredentialInput struct {
	ID       string          `json:"id,omitempty"`
	Kind     string          `json:"kind"`
	Label    string          `json:"label"`
	Revision int64           `json:"revision"`
	Secret   json.RawMessage `json:"secret,omitempty"`
}
type CredentialView struct {
	ID       string `json:"id"`
	Kind     string `json:"kind"`
	Label    string `json:"label"`
	Revision int64  `json:"revision"`
}
type CredentialSecret struct {
	APIKey          string `json:"api_key,omitempty"`
	Username        string `json:"username,omitempty"`
	Password        string `json:"password,omitempty"`
	AccessKeyID     string `json:"access_key_id,omitempty"`
	AccessKeySecret string `json:"access_key_secret,omitempty"`
	SecurityToken   string `json:"security_token,omitempty"`
	Token           string `json:"token,omitempty"`
}

func (s *Store) SaveCredential(v protocol.Viewer, in CredentialInput) (CredentialView, error) {
	empty := CredentialView{}
	if !isAdmin(v) {
		return empty, ErrForbidden
	}
	if in.Label == "" || len(in.Label) > 120 || len(in.Secret) > 16384 || in.Revision < 0 {
		return empty, ErrInvalid
	}
	var secret CredentialSecret
	if len(in.Secret) > 0 {
		d := json.NewDecoder(strings.NewReader(string(in.Secret)))
		d.DisallowUnknownFields()
		if d.Decode(&secret) != nil {
			return empty, ErrInvalid
		}
		switch in.Kind {
		case "http", "dify", "deepseek", "heartbeat":
			if secret.APIKey == "" || (in.Kind == "heartbeat" && len(secret.APIKey) < 32) {
				return empty, ErrInvalid
			}
		case "postgres":
			if secret.Username == "" || secret.Password == "" {
				return empty, ErrInvalid
			}
		case "qwen":
			if secret.AccessKeyID == "" || secret.AccessKeySecret == "" {
				return empty, ErrInvalid
			}
		case "notification":
			if secret.Token == "" {
				return empty, ErrInvalid
			}
		default:
			return empty, ErrInvalid
		}
	}
	if in.ID == "" {
		in.ID = newID()
	}
	tx, err := s.db.Begin()
	if err != nil {
		return empty, err
	}
	defer tx.Rollback()
	now := time.Now().UnixMilli()
	var currentKind, sealed string
	if in.Revision > 0 {
		if tx.QueryRow(`SELECT kind,sealed_value FROM credentials WHERE id=? AND revision=?`, in.ID, in.Revision).Scan(&currentKind, &sealed) != nil || currentKind != in.Kind {
			return empty, ErrConflict
		}
	}
	if len(in.Secret) > 0 {
		sealed, err = s.seal(in.ID, in.Kind, in.Secret)
		if err != nil {
			return empty, err
		}
	} else if sealed == "" {
		return empty, ErrInvalid
	}
	if in.Revision == 0 {
		_, err = tx.Exec(`INSERT INTO credentials(id,kind,label,sealed_value,revision,created_at,updated_at) VALUES(?,?,?,?,1,?,?)`, in.ID, in.Kind, in.Label, sealed, now, now)
	} else {
		var result sql.Result
		result, err = tx.Exec(`UPDATE credentials SET label=?,sealed_value=?,revision=revision+1,updated_at=? WHERE id=? AND revision=?`, in.Label, sealed, now, in.ID, in.Revision)
		if err == nil {
			n, _ := result.RowsAffected()
			if n != 1 {
				return empty, ErrConflict
			}
		}
	}
	if err != nil {
		return empty, ErrConflict
	}
	if len(in.Secret) > 0 {
		if err := closeEvidence(tx, "m.credential_id=?", []any{in.ID}, now); err != nil {
			return empty, err
		}
		rows, err := tx.Query(`SELECT id FROM monitors WHERE credential_id=?`, in.ID)
		if err != nil {
			return empty, err
		}
		ids := []string{}
		for rows.Next() {
			var id string
			if rows.Scan(&id) != nil {
				rows.Close()
				return empty, ErrInvalid
			}
			ids = append(ids, id)
		}
		err = rows.Err()
		rows.Close()
		if err != nil {
			return empty, err
		}
		for _, id := range ids {
			if err := audit(tx, v, "monitor.reset", id, now); err != nil {
				return empty, err
			}
		}
		for _, q := range []string{`UPDATE monitors SET revision=revision+1,lease_token='',lease_until=0 WHERE credential_id=?`, `UPDATE monitor_states SET current_state='unknown',success_streak=0,failure_streak=0,last_observation_id=NULL,last_success_at=0 WHERE monitor_id IN(SELECT id FROM monitors WHERE credential_id=?)`, `UPDATE notification_publishers SET enabled=0,revision=revision+1 WHERE credential_id=?`} {
			if _, err := tx.Exec(q, in.ID); err != nil {
				return empty, err
			}
		}
	}
	if err := audit(tx, v, "credential.save", in.ID, now); err != nil {
		return empty, err
	}
	if err := tx.Commit(); err != nil {
		return empty, err
	}
	return CredentialView{in.ID, in.Kind, in.Label, in.Revision + 1}, nil
}
func (s *Store) DeleteCredential(v protocol.Viewer, id string, revision int64) error {
	if !isAdmin(v) {
		return ErrForbidden
	}
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	result, err := tx.Exec(`DELETE FROM credentials WHERE id=? AND revision=?`, id, revision)
	if err != nil {
		return ErrConflict
	}
	n, _ := result.RowsAffected()
	if n != 1 {
		return ErrConflict
	}
	if err := audit(tx, v, "credential.delete", id, time.Now().UnixMilli()); err != nil {
		return err
	}
	return tx.Commit()
}

type ComponentView struct {
	ID         string        `json:"id"`
	Label      string        `json:"label"`
	State      string        `json:"state"`
	UpdatedAt  string        `json:"updated_at"`
	Monitors   []MonitorView `json:"monitors,omitempty"`
	ObservedAt string        `json:"observed_at"`
	Stale      bool          `json:"stale"`
}
type MonitorView struct {
	Outcome         string          `json:"outcome"`
	ID              string          `json:"id"`
	Label           string          `json:"label"`
	Kind            string          `json:"kind"`
	State           string          `json:"state"`
	ObservedAt      string          `json:"observed_at"`
	Measurements    json.RawMessage `json:"measurements,omitempty"`
	LastSuccessAt   string          `json:"last_success_at"`
	NextCheckAt     string          `json:"next_check_at"`
	ReasonCode      string          `json:"reason_code"`
	Stale           bool            `json:"stale"`
	IntervalSeconds int             `json:"interval_seconds"`
	TimeoutSeconds  int             `json:"timeout_seconds"`
}

func (s *Store) Components(v protocol.Viewer, public bool, now time.Time) ([]ComponentView, error) {
	out := []ComponentView{}
	if public && s.setting("public_enabled") != "1" {
		return out, nil
	}
	filter, args := componentFilter(v, "c", public)
	paused := s.setting("probes_paused") == "1"
	query := `SELECT c.id,c.label,c.public_label,c.updated_at FROM components c WHERE c.enabled=1 AND ` + filter + ` ORDER BY c.created_at,c.id LIMIT 100`
	rows, err := s.db.Query(query, args...)
	if err != nil {
		return nil, err
	}
	type row struct {
		id, label, publicLabel string
		updated                int64
	}
	all := []row{}
	for rows.Next() {
		var c row
		if err := rows.Scan(&c.id, &c.label, &c.publicLabel, &c.updated); err != nil {
			rows.Close()
			return nil, err
		}
		all = append(all, c)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return nil, err
	}
	for _, c := range all {
		if !public && !s.canRead(v, c.id, "read") {
			continue
		}
		label := c.label
		if public {
			label = c.publicLabel
		}
		component := ComponentView{ID: c.id, Label: label, State: "unknown", UpdatedAt: utc(c.updated)}
		monitors, err := s.monitorViews(c.id, !public && s.canRead(v, c.id, "finance"), now)
		if err != nil {
			return nil, err
		}
		component.Stale = len(monitors) == 0 || paused
		oldest := int64(0)
		missing := false
		for _, monitor := range monitors {
			component.Stale = component.Stale || monitor.Stale
			if monitor.ObservedAt == "" {
				missing = true
				continue
			}
			instant, err := time.Parse(time.RFC3339Nano, monitor.ObservedAt)
			if err != nil {
				missing = true
				continue
			}
			if oldest == 0 || instant.UnixMilli() < oldest {
				oldest = instant.UnixMilli()
			}
		}
		if !missing {
			component.ObservedAt = utc(oldest)
		}
		component.State = reduceComponent(monitors)
		var maintenance int
		s.db.QueryRow(`SELECT COUNT(*) FROM maintenance_windows WHERE component_id=? AND starts_at<=? AND ends_at>?`, c.id, now.UnixMilli(), now.UnixMilli()).Scan(&maintenance)
		if maintenance > 0 {
			component.State = "maintenance"
		}
		if paused {
			component.State = "paused"
		}
		if !public {
			component.Monitors = monitors
		}
		out = append(out, component)
	}
	return out, nil
}
func (s *Store) monitorViews(component string, finance bool, now time.Time) ([]MonitorView, error) {
	var maintenanceEnd int64
	if err := s.db.QueryRow(`SELECT COALESCE(MAX(ends_at),0) FROM maintenance_windows WHERE component_id=? AND ends_at<=?`, component, now.UnixMilli()).Scan(&maintenanceEnd); err != nil {
		return nil, err
	}
	rows, err := s.db.Query(`SELECT m.id,m.label,m.kind,m.interval_seconds,m.timeout_seconds,COALESCE(s.current_state,'unknown'),COALESCE(o.observed_at,0),COALESCE(o.measurements,'{}'),COALESCE(s.last_success_at,0),m.next_at,COALESCE(o.reason_code,''),COALESCE(o.outcome,'unknown') FROM monitors m LEFT JOIN monitor_states s ON s.monitor_id=m.id LEFT JOIN observations o ON o.id=s.last_observation_id WHERE m.component_id=? AND m.enabled=1 ORDER BY m.id LIMIT 32`, component)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []MonitorView{}
	for rows.Next() {
		var m MonitorView
		var interval, timeout int
		var updated, lastSuccess, next int64
		var metrics string
		if err := rows.Scan(&m.ID, &m.Label, &m.Kind, &interval, &timeout, &m.State, &updated, &metrics, &lastSuccess, &next, &m.ReasonCode, &m.Outcome); err != nil {
			return nil, err
		}
		ttl := max(3*interval, 2*timeout)
		if updated == 0 || updated < maintenanceEnd || now.UnixMilli()-updated > int64(ttl)*1000 {
			m.State = "unknown"
			m.Stale = true
		}
		m.IntervalSeconds, m.TimeoutSeconds = interval, timeout
		m.LastSuccessAt, m.NextCheckAt = utc(lastSuccess), utc(next)
		m.ObservedAt = utc(updated)
		if finance {
			var safe Measurements
			json.Unmarshal([]byte(metrics), &safe)
			m.Measurements, _ = json.Marshal(safe)
		} else {
			var safe struct {
				LatencyMS  int64  `json:"latency_ms,omitempty"`
				Capability string `json:"capability,omitempty"`
			}
			json.Unmarshal([]byte(metrics), &safe)
			m.Measurements, _ = json.Marshal(safe)
		}
		out = append(out, m)
	}
	return out, rows.Err()
}
func reduceComponent(monitors []MonitorView) string {
	if len(monitors) == 0 {
		return "unknown"
	}
	state := "operational"
	for _, m := range monitors {
		switch m.State {
		case "outage":
			return "outage"
		case "degraded":
			state = "degraded"
		case "unknown":
			if state == "operational" {
				state = "unknown"
			}
		}
	}
	return state
}
