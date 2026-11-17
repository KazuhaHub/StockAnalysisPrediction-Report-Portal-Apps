package status

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"sync"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

type Server struct {
	publicBudget publicBudget
	store        *Store
	registration string
	bootID       string
	slots        chan struct{}

	verifierMu  sync.Mutex
	verifier    *protocol.Verifier
	verifierKey string
}

// NewServer serves the application's HTTP interface on behalf of the platform.
// The registration file supplies the only key that can authenticate requests
// and the boot identity binds every assertion to this process.
func NewServer(store *Store, registration, bootID string) *Server {
	return &Server{store: store, registration: registration, bootID: bootID, slots: make(chan struct{}, 16)}
}

// verifierFor returns the verifier for the current registration. The replay set
// lives as long as the registration is unchanged; a rotated key replaces it, and
// assertions made under the old key no longer verify anyway.
func (s *Server) verifierFor() (*protocol.Verifier, error) {
	registration, err := LoadRegistration(s.registration)
	defer clear(registration.Key)
	if err != nil {
		return nil, err
	}
	signer, err := registration.Signer(s.bootID)
	if err != nil {
		return nil, err
	}
	defer clear(signer.Key)
	fingerprint := signer.Issuer + "\x00" + signer.Audience + "\x00" + signer.InstanceID + "\x00" + signer.KeyID
	s.verifierMu.Lock()
	defer s.verifierMu.Unlock()
	if s.verifier == nil || s.verifierKey != fingerprint {
		s.verifier = protocol.NewVerifier(protocol.VerifyConfig{Issuer: signer.Issuer, Audience: signer.Audience, AppID: signer.AppID, InstanceID: signer.InstanceID, BootID: signer.BootID, Keys: map[string][]byte{signer.KeyID: signer.Key}})
		s.verifierKey = fingerprint
	}
	return s.verifier, nil
}

func write(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(value)
}
func apiError(w http.ResponseWriter, err error) {
	status, code := 503, "unavailable"
	switch {
	case errors.Is(err, ErrForbidden):
		status, code = 403, "forbidden"
	case errors.Is(err, ErrConflict):
		status, code = 409, "conflict"
	case errors.Is(err, ErrInvalid):
		status, code = 400, "invalid_configuration"
	case errors.Is(err, ErrNotFound):
		status, code = 404, "not_found"
	}
	// SQL, network and credential errors never enter wire messages.
	write(w, status, map[string]any{"ok": false, "error": map[string]string{"code": code}})
}
func (s *Server) handshake(w http.ResponseWriter, r *http.Request, raw []byte) {
	if r.URL.RawQuery != "" || r.Header.Get("Cookie") != "" || r.Header.Get("Authorization") != "" || r.Header.Get("Content-Type") != "application/json" {
		write(w, 400, map[string]bool{"ok": false})
		return
	}
	var in struct {
		Challenge string `json:"challenge"`
	}
	if len(raw) == 0 || len(raw) > maxHandshakeBody || strictJSON(raw, &in) != nil || in.Challenge == "" || len(in.Challenge) > maxChallengeLength {
		write(w, 400, map[string]bool{"ok": false})
		return
	}
	registration, err := LoadRegistration(s.registration)
	defer clear(registration.Key)
	if err != nil {
		write(w, 503, map[string]bool{"ok": false})
		return
	}
	signer, err := registration.Signer(s.bootID)
	if err != nil {
		write(w, 503, map[string]bool{"ok": false})
		return
	}
	defer clear(signer.Key)
	answer, err := signer.AnswerChallenge(in.Challenge, s.bootID, time.Now())
	if err != nil {
		write(w, 400, map[string]bool{"ok": false})
		return
	}
	write(w, 200, map[string]string{"answer": answer})
}
func decode(raw []byte, out any) error {
	d := json.NewDecoder(bytes.NewReader(raw))
	d.DisallowUnknownFields()
	if err := d.Decode(out); err != nil {
		return ErrInvalid
	}
	var extra any
	if d.Decode(&extra) != io.EOF {
		return ErrInvalid
	}
	return nil
}
func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	select {
	case s.slots <- struct{}{}:
		defer func() { <-s.slots }()
	default:
		write(w, 429, map[string]any{"ok": false})
		return
	}
	raw, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 65536))
	if err != nil {
		apiError(w, ErrInvalid)
		return
	}
	if r.URL.Path == "/v1/handshake" {
		if r.Method == "POST" {
			s.handshake(w, r, raw)
		} else {
			http.NotFound(w, r)
		}
		return
	}
	if r.URL.Path == "/health/ready" {
		if r.Method != "GET" {
			http.NotFound(w, r)
			return
		}
		if r.URL.RawQuery != "" || r.Header.Get("Authorization") != "" || r.Header.Get("Cookie") != "" {
			write(w, 400, map[string]bool{"ok": false})
			return
		}
		var n int
		if err := s.store.db.QueryRowContext(r.Context(), `SELECT 1`).Scan(&n); err != nil {
			write(w, 503, map[string]bool{"ok": false})
			return
		}
		write(w, 200, map[string]any{"protocol": backendProtocolVersion, "ready": true, "data_format": backendDataFormatVersion})
		return
	}
	if !strings.HasPrefix(r.URL.Path, "/v1/") {
		http.NotFound(w, r)
		return
	}
	// The relay passes a backend answer on only for 2xx and 400, 403, 404, 409,
	// 422 and 429, so a rejected assertion or viewer is a 403, not a 401.
	headers := r.Header.Values(protocol.Header)
	if len(headers) != 1 {
		write(w, 403, map[string]bool{"ok": false})
		return
	}
	verifier, err := s.verifierFor()
	if err != nil {
		write(w, 503, map[string]bool{"ok": false})
		return
	}
	claims, err := verifier.Verify(headers[0], r.Method, r.URL.RequestURI(), raw, time.Now())
	if err != nil {
		write(w, 403, map[string]bool{"ok": false})
		return
	}
	v := claims.Viewer
	if _, ok := authorityOf(v); !ok {
		write(w, 403, map[string]bool{"ok": false})
		return
	}
	if r.Method != "GET" || strings.HasPrefix(r.URL.Path, "/v1/manage/") {
		if !isAdmin(v) {
			apiError(w, ErrForbidden)
			return
		}
	}
	switch {
	case r.Method == "GET" && r.URL.Path == "/v1/me":
		write(w, 200, map[string]any{"ok": true, "admin": isAdmin(v), "api_version": 1, "capabilities": []string{"status.components.v1", "status.history.v2", "status.export.v1", "status.retention.v1", "status.postgres-unix.v1"}})
	case r.Method == "GET" && r.URL.Path == "/v1/components":
		offset, limit, err := pageParams(r)
		if err != nil {
			apiError(w, err)
			return
		}
		out, err := s.store.ComponentPage(v, time.Now(), offset, limit, r.URL.Query().Get("q"))
		if err != nil {
			apiError(w, err)
			return
		}
		write(w, 200, out)
	case r.Method == "PUT" && r.URL.Path == "/v1/manage/components":
		var in ComponentInput
		if decode(raw, &in) != nil {
			apiError(w, ErrInvalid)
			return
		}
		out, err := s.store.SaveComponent(v, in)
		if err != nil {
			apiError(w, err)
			return
		}
		write(w, 200, map[string]any{"ok": true, "item": out})
	case r.Method == "GET" && r.URL.Path == "/v1/manage/components":
		out, err := s.store.ComponentConfigurations()
		if err != nil {
			apiError(w, err)
			return
		}
		write(w, 200, map[string]any{"ok": true, "items": out})
	case r.Method == "GET" && r.URL.Path == "/v1/manage/credentials":
		rows, err := s.store.db.QueryContext(r.Context(), `SELECT id,kind,label,revision FROM credentials ORDER BY created_at,id LIMIT 100`)
		if err != nil {
			apiError(w, err)
			return
		}
		defer rows.Close()
		out := []CredentialView{}
		for rows.Next() {
			var c CredentialView
			if rows.Scan(&c.ID, &c.Kind, &c.Label, &c.Revision) != nil {
				apiError(w, ErrInvalid)
				return
			}
			out = append(out, c)
		}
		if err := rows.Err(); err != nil {
			apiError(w, err)
			return
		}
		write(w, 200, map[string]any{"ok": true, "items": out})
	case r.Method == "PUT" && r.URL.Path == "/v1/manage/credentials":
		var in CredentialInput
		if decode(raw, &in) != nil {
			apiError(w, ErrInvalid)
			return
		}
		out, err := s.store.SaveCredential(v, in)
		if err != nil {
			apiError(w, err)
			return
		}
		write(w, 200, map[string]any{"ok": true, "item": out})
	case r.Method == "DELETE" && r.URL.Path == "/v1/manage/credentials":
		var in struct {
			ID       string `json:"id"`
			Revision int64  `json:"revision"`
		}
		if decode(raw, &in) != nil {
			apiError(w, ErrInvalid)
			return
		}
		if err := s.store.DeleteCredential(v, in.ID, in.Revision); err != nil {
			apiError(w, err)
			return
		}
		write(w, 200, map[string]bool{"ok": true})
	default:
		if !s.moreRoutes(w, r, raw, v) {
			apiError(w, ErrNotFound)
		}
	}
}
func (s *Store) ComponentConfigurations() ([]ComponentInput, error) {
	rows, err := s.db.Query(`SELECT id,label,public_label,public_enabled,enabled,revision FROM components ORDER BY created_at,id LIMIT 100`)
	if err != nil {
		return nil, err
	}
	out := []ComponentInput{}
	for rows.Next() {
		var c ComponentInput
		if rows.Scan(&c.ID, &c.Label, &c.PublicLabel, &c.PublicEnabled, &c.Enabled, &c.Revision) != nil {
			rows.Close()
			return nil, ErrInvalid
		}
		out = append(out, c)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return nil, err
	}
	for i := range out {
		c := &out[i]
		c.Grants = []Grant{}
		c.Monitors = []MonitorInput{}
		rows, err := s.db.Query(`SELECT principal,permission FROM component_grants WHERE component_id=? ORDER BY principal,permission`, c.ID)
		if err != nil {
			return nil, err
		}
		for rows.Next() {
			var g Grant
			if rows.Scan(&g.Principal, &g.Permission) != nil {
				rows.Close()
				return nil, ErrInvalid
			}
			c.Grants = append(c.Grants, g)
		}
		err = rows.Err()
		rows.Close()
		if err != nil {
			return nil, err
		}
		rows, err = s.db.Query(`SELECT id,kind,label,COALESCE(credential_id,''),config,enabled,interval_seconds,timeout_seconds,revision FROM monitors WHERE component_id=? ORDER BY created_at,id LIMIT 32`, c.ID)
		if err != nil {
			return nil, err
		}
		for rows.Next() {
			var m MonitorInput
			var config string
			if rows.Scan(&m.ID, &m.Kind, &m.Label, &m.CredentialID, &config, &m.Enabled, &m.IntervalSeconds, &m.TimeoutSeconds, &m.Revision) != nil {
				rows.Close()
				return nil, ErrInvalid
			}
			m.Config = json.RawMessage(config)
			c.Monitors = append(c.Monitors, m)
		}
		err = rows.Err()
		rows.Close()
		if err != nil {
			return nil, err
		}
	}
	return out, nil
}

// servePhase2 holds the routes that need Portal capabilities the platform does
// not offer yet: anonymous public pages and inbound heartbeat ingress. It is
// deliberately not called from ServeHTTP, so the platform socket serves none
// of them. Phase 2 registers it once the platform can carry those requests.
func (s *Server) servePhase2(w http.ResponseWriter, r *http.Request, raw []byte) bool {
	if (r.URL.Path == "/" || r.URL.Path == "/app.js" || r.URL.Path == "/style.css" || strings.HasPrefix(r.URL.Path, "/public/")) && !s.publicBudget.allow(r.RemoteAddr, time.Now()) {
		w.Header().Set("Retry-After", "1")
		write(w, 429, map[string]bool{"ok": false})
		return true
	}
	if s.publicRoute(w, r) {
		return true
	}
	if r.Method == "POST" && strings.HasPrefix(r.URL.Path, "/ingest/v1/heartbeats/") {
		s.heartbeat(w, r, raw)
		return true
	}
	if r.Method == "GET" && r.URL.Path == "/public/v1/status" {
		offset, limit, err := pageParams(r)
		if err != nil {
			apiError(w, err)
			return true
		}
		page, err := s.store.PublicComponentPage(time.Now(), offset, limit)
		if err != nil {
			apiError(w, err)
			return true
		}
		// Explicit projection: adding fields to private views cannot publish them.
		type publicComponent struct {
			ID         string `json:"id"`
			Label      string `json:"label"`
			State      string `json:"state"`
			ObservedAt string `json:"observed_at"`
			Stale      bool   `json:"stale"`
		}
		out := []publicComponent{}
		for _, c := range page.Items {
			out = append(out, publicComponent{c.ID, c.Label, c.State, c.ObservedAt, c.Stale})
		}
		w.Header().Set("Cache-Control", "public, max-age=10")
		write(w, 200, map[string]any{"ok": true, "items": out, "total": page.Total, "offset": page.Offset, "limit": page.Limit, "generated_at": time.Now().UTC().Format(time.RFC3339)})
		return true
	}
	return false
}
