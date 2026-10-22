package status

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"strings"
	"time"
)

func (s *Server) heartbeat(w http.ResponseWriter, r *http.Request, raw []byte) {
	deny := func() { write(w, 401, map[string]bool{"ok": false}) }
	id := strings.TrimPrefix(r.URL.Path, "/ingest/v1/heartbeats/")
	if len(id) != 32 || strings.Contains(id, "/") || len(raw) > 1024 {
		deny()
		return
	}
	var in struct {
		Timestamp string `json:"timestamp"`
		Nonce     string `json:"nonce"`
	}
	if decode(raw, &in) != nil || len(in.Nonce) < 16 || len(in.Nonce) > 128 {
		deny()
		return
	}
	at, err := time.Parse(time.RFC3339, in.Timestamp)
	if err != nil || at.Before(time.Now().Add(-30*time.Second)) || at.After(time.Now().Add(5*time.Second)) {
		deny()
		return
	}
	tx, err := s.store.db.Begin()
	if err != nil {
		apiError(w, err)
		return
	}
	defer tx.Rollback()
	var sealed, credential, kind string
	var revision int64
	err = tx.QueryRow(`SELECT c.sealed_value,c.id,c.kind,m.revision FROM monitors m JOIN components p ON p.id=m.component_id JOIN credentials c ON c.id=m.credential_id WHERE m.id=? AND m.kind='heartbeat' AND m.enabled=1 AND p.enabled=1`, id).Scan(&sealed, &credential, &kind, &revision)
	if err != nil || kind != "heartbeat" {
		deny()
		return
	}
	plain, err := s.store.open(credential, kind, sealed)
	if err != nil {
		deny()
		return
	}
	var secret CredentialSecret
	if json.Unmarshal(plain, &secret) != nil {
		deny()
		return
	}
	signature, err := hex.DecodeString(r.Header.Get("X-Status-Signature"))
	if err != nil {
		deny()
		return
	}
	mac := hmac.New(sha256.New, []byte(secret.APIKey))
	mac.Write([]byte(id + "\n"))
	mac.Write(raw)
	if !hmac.Equal(signature, mac.Sum(nil)) {
		deny()
		return
	}
	// Persist the nonce as the observation identity so a service restart cannot
	// reset replay protection. Timestamp bounds make retained tombstones sufficient.
	nonce := hashHex([]byte(id + ":" + in.Nonce))
	now := time.Now().UnixMilli()
	var recent int
	if err := tx.QueryRow(`SELECT COUNT(*) FROM observations WHERE monitor_id=? AND outcome='heartbeat' AND observed_at>?`, id, now-60000).Scan(&recent); err != nil {
		apiError(w, err)
		return
	}
	if recent >= 10 {
		write(w, 429, map[string]bool{"ok": false})
		return
	}
	if _, err := tx.Exec(`INSERT INTO observations(id,monitor_id,monitor_revision,outcome,reason_code,measurements,observed_at,duration_ms) VALUES(?,?,?,'heartbeat','heartbeat_received','{}',?,0)`, nonce, id, revision, now); err != nil {
		deny()
		return
	}
	if err := tx.Commit(); err != nil {
		apiError(w, err)
		return
	}
	write(w, 202, map[string]bool{"ok": true})
}
func (s *Store) HeartbeatResult(m Monitor, now time.Time) Result {
	var observed int64
	err := s.db.QueryRow(`SELECT COALESCE(MAX(observed_at),0) FROM observations WHERE monitor_id=? AND monitor_revision=? AND outcome='heartbeat'`, m.ID, m.Revision).Scan(&observed)
	if err != nil {
		return unknown("observer_unavailable")
	}
	if observed == 0 {
		return unknown("heartbeat_not_received")
	}
	if now.UnixMilli()-observed > int64(3*m.IntervalSeconds)*1000 {
		return Result{Outcome: "failure", ReasonCode: "heartbeat_missed"}
	}
	return Result{Outcome: "success", ReasonCode: "heartbeat_received", Measurements: Measurements{Capability: "heartbeat_freshness"}}
}
