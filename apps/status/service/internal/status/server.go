package status

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

type Server struct {
	publicBudget publicBudget
	store        *Store
	signer       protocol.Signer
	verifier     *protocol.Verifier
	slots        chan struct{}
}

func NewServer(store *Store, signer protocol.Signer) (*Server, error) {
	if _, err := signer.NewChallenge(time.Now()); err != nil {
		return nil, err
	}
	signer.BootID = newID()
	return &Server{store: store, signer: signer, verifier: protocol.NewVerifier(protocol.VerifyConfig{Issuer: signer.Issuer, Audience: signer.Audience, AppID: signer.AppID, InstanceID: signer.InstanceID, BootID: signer.BootID, Keys: map[string][]byte{signer.KeyID: signer.Key}}), slots: make(chan struct{}, 16)}, nil
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
	if (r.URL.Path == "/" || r.URL.Path == "/app.js" || r.URL.Path == "/style.css" || strings.HasPrefix(r.URL.Path, "/public/")) && !s.publicBudget.allow(r.RemoteAddr, time.Now()) {
		w.Header().Set("Retry-After", "1")
		write(w, 429, map[string]bool{"ok": false})
		return
	}
	if s.publicRoute(w, r) {
		return
	}
	if r.Method == "POST" && strings.HasPrefix(r.URL.Path, "/ingest/v1/heartbeats/") {
		s.heartbeat(w, r, raw)
		return
	}
	if r.Method == "POST" && r.URL.Path == "/v1/handshake" {
		var in struct {
			Challenge string `json:"challenge"`
		}
		if len(raw) > 8192 || decode(raw, &in) != nil {
			apiError(w, ErrInvalid)
			return
		}
		answer, err := s.signer.AnswerChallenge(in.Challenge, s.signer.BootID, time.Now())
		if err != nil {
			write(w, 401, map[string]any{"ok": false})
			return
		}
		write(w, 200, map[string]string{"answer": answer})
		return
	}
	if r.Method == "GET" && r.URL.Path == "/healthz" {
		var n int
		if err := s.store.db.QueryRowContext(r.Context(), `SELECT 1`).Scan(&n); err != nil {
			write(w, 503, map[string]bool{"ok": false})
		} else {
			write(w, 200, map[string]bool{"ok": true})
		}
		return
	}
	if r.Method == "GET" && r.URL.Path == "/public/v1/status" {
		components, err := s.store.Components(protocol.Viewer{}, true, time.Now())
		if err != nil {
			apiError(w, err)
			return
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
		for _, c := range components {
			out = append(out, publicComponent{c.ID, c.Label, c.State, c.ObservedAt, c.Stale})
		}
		w.Header().Set("Cache-Control", "public, max-age=10")
		write(w, 200, map[string]any{"ok": true, "items": out, "generated_at": time.Now().UTC().Format(time.RFC3339)})
		return
	}
	headers := r.Header.Values(protocol.Header)
	if len(headers) != 1 {
		write(w, 401, map[string]bool{"ok": false})
		return
	}
	claims, err := s.verifier.Verify(headers[0], r.Method, r.URL.RequestURI(), raw, time.Now())
	if err != nil {
		write(w, 401, map[string]bool{"ok": false})
		return
	}
	v := claims.Viewer
	if r.Method != "GET" || strings.HasPrefix(r.URL.Path, "/v1/manage/") {
		if !isAdmin(v) {
			apiError(w, ErrForbidden)
			return
		}
	}
	switch {
	case r.Method == "GET" && r.URL.Path == "/v1/me":
		write(w, 200, map[string]any{"ok": true, "admin": isAdmin(v)})
	case r.Method == "GET" && r.URL.Path == "/v1/components":
		out, err := s.store.Components(v, false, time.Now())
		if err != nil {
			apiError(w, err)
			return
		}
		write(w, 200, map[string]any{"ok": true, "items": out})
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
