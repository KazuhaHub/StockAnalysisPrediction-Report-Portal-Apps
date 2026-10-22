package status

import (
	"embed"
	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
	"net/http"
	"strings"
)

//go:embed public/*
var publicAssets embed.FS

func (s *Server) publicRoute(w http.ResponseWriter, r *http.Request) bool {
	if r.Method != "GET" {
		return false
	}
	path := r.URL.Path
	if path == "/readyz" {
		var n int
		if s.store.db.QueryRowContext(r.Context(), `SELECT 1`).Scan(&n) != nil {
			write(w, 503, map[string]bool{"ok": false})
		} else {
			write(w, 200, map[string]bool{"ok": true})
		}
		return true
	}
	if path == "/public/v1/incidents" {
		offset, limit, err := pageParams(r)
		if err != nil {
			apiError(w, err)
			return true
		}
		page, err := s.store.Incidents(protocol.Viewer{}, true, offset, limit)
		if err != nil {
			apiError(w, err)
			return true
		}
		// Keep the public DTO independent of all future private history fields.
		type publicIncident struct {
			ID          string `json:"id"`
			ComponentID string `json:"component_id"`
			State       string `json:"state"`
			Summary     string `json:"summary"`
			OpenedAt    string `json:"opened_at"`
			ResolvedAt  string `json:"resolved_at"`
		}
		items := []publicIncident{}
		for _, i := range page.Items {
			items = append(items, publicIncident{i.ID, i.ComponentID, i.State, i.Summary, i.OpenedAt, i.ResolvedAt})
		}
		w.Header().Set("Cache-Control", "public, max-age=10")
		write(w, 200, map[string]any{"items": items, "total": page.Total, "offset": page.Offset, "limit": page.Limit})
		return true
	}
	if path != "/" && path != "/app.js" && path != "/style.css" {
		return false
	}
	if s.store.setting("public_enabled") != "1" {
		http.NotFound(w, r)
		return true
	}
	name := strings.TrimPrefix(path, "/")
	if name == "" {
		name = "index.html"
	}
	body, err := publicAssets.ReadFile("public/" + name)
	if err != nil {
		http.NotFound(w, r)
		return true
	}
	content := map[string]string{"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8", "style.css": "text/css; charset=utf-8"}[name]
	w.Header().Set("Content-Type", content)
	w.Header().Set("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
	w.Header().Set("Referrer-Policy", "no-referrer")
	w.WriteHeader(200)
	w.Write(body)
	return true
}
