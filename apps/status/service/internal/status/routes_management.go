package status

import (
	"net/http"
	"strconv"
	"strings"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

func pageParams(r *http.Request) (int, int, error) {
	offset, limit := 0, 50
	var err error
	if text := r.URL.Query().Get("offset"); text != "" {
		offset, err = strconv.Atoi(text)
		if err != nil {
			return 0, 0, ErrInvalid
		}
	}
	if text := r.URL.Query().Get("limit"); text != "" {
		limit, err = strconv.Atoi(text)
		if err != nil {
			return 0, 0, ErrInvalid
		}
	}
	if offset < 0 || offset > 1000000 || limit < 1 || limit > 100 {
		return 0, 0, ErrInvalid
	}
	return offset, limit, nil
}
func (s *Server) moreRoutes(w http.ResponseWriter, r *http.Request, raw []byte, v protocol.Viewer) bool {
	path := r.URL.Path
	switch {
	case r.Method == "GET" && path == "/v1/incidents":
		offset, limit, err := pageParams(r)
		if err != nil {
			apiError(w, err)
			return true
		}
		out, err := s.store.Incidents(v, false, offset, limit)
		if err != nil {
			apiError(w, err)
			return true
		}
		write(w, 200, out)
	case r.Method == "GET" && strings.HasPrefix(path, "/v1/incidents/"):
		out, err := s.store.Incident(v, strings.TrimPrefix(path, "/v1/incidents/"), false)
		if err != nil {
			apiError(w, err)
			return true
		}
		write(w, 200, map[string]any{"ok": true, "item": out})
	case r.Method == "GET" && path == "/v1/history/hourly":
		from, to, err := parseRange(r.URL.Query().Get("from"), r.URL.Query().Get("to"))
		if err != nil {
			apiError(w, err)
			return true
		}
		out, err := s.store.HourlyHistory(v, r.URL.Query().Get("component_id"), from, to)
		if err != nil {
			apiError(w, err)
			return true
		}
		write(w, 200, map[string]any{"ok": true, "items": out, "semantics": "worst_observed_state_with_unknown_coverage"})
	case r.Method == "GET" && path == "/v1/history":
		from, to, err := parseRange(r.URL.Query().Get("from"), r.URL.Query().Get("to"))
		if err != nil {
			apiError(w, err)
			return true
		}
		out, err := s.store.History(v, r.URL.Query().Get("component_id"), from, to)
		if err != nil {
			apiError(w, err)
			return true
		}
		write(w, 200, map[string]any{"ok": true, "items": out, "from": utc(from.UnixMilli()), "to": utc(to.UnixMilli()), "buckets": "clipped_utc_intervals"})
	case r.Method == "GET" && path == "/v1/manage/operations":
		fingerprint, err := s.store.QueueFingerprint()
		if err != nil {
			apiError(w, err)
			return true
		}
		outbox, err := s.store.OutboxViews()
		if err != nil {
			apiError(w, err)
			return true
		}
		publishers, err := s.store.PublisherViews()
		if err != nil {
			apiError(w, err)
			return true
		}
		write(w, 200, map[string]any{"ok": true, "settings": s.store.Settings(), "queue_fingerprint": fingerprint, "outbox": outbox, "publishers": publishers})
	case r.Method == "PUT" && path == "/v1/manage/settings":
		var in ServiceSettings
		if decode(raw, &in) != nil {
			apiError(w, ErrInvalid)
			return true
		}
		if err := s.store.SaveSettings(v, in); err != nil {
			apiError(w, err)
			return true
		}
		write(w, 200, map[string]bool{"ok": true})
	case r.Method == "POST" && path == "/v1/manage/probes/request":
		var in struct {
			ID       string `json:"id"`
			Revision int64  `json:"revision"`
		}
		if decode(raw, &in) != nil {
			apiError(w, ErrInvalid)
			return true
		}
		if err := s.store.RequestProbe(v, in.ID, in.Revision); err != nil {
			apiError(w, err)
			return true
		}
		write(w, 202, map[string]any{"ok": true, "state": "queued"})
	case r.Method == "POST" && path == "/v1/manage/resume":
		var in struct {
			Fingerprint string `json:"queue_fingerprint"`
			Probes      bool   `json:"probes"`
			Outbox      bool   `json:"outbox"`
		}
		if decode(raw, &in) != nil {
			apiError(w, ErrInvalid)
			return true
		}
		if err := s.store.Resume(v, in.Fingerprint, in.Probes, in.Outbox); err != nil {
			apiError(w, err)
			return true
		}
		write(w, 200, map[string]bool{"ok": true})
	case r.Method == "PUT" && path == "/v1/manage/publishers":
		var in PublisherInput
		if decode(raw, &in) != nil {
			apiError(w, ErrInvalid)
			return true
		}
		if err := s.store.SavePublisher(v, in); err != nil {
			apiError(w, err)
			return true
		}
		write(w, 200, map[string]bool{"ok": true})
	case r.Method == "POST" && path == "/v1/manage/outbox/review":
		var in struct {
			ID          string `json:"id"`
			Fingerprint string `json:"queue_fingerprint"`
			Action      string `json:"action"`
		}
		if decode(raw, &in) != nil {
			apiError(w, ErrInvalid)
			return true
		}
		if err := s.store.ReviewNotice(v, in.ID, in.Fingerprint, in.Action); err != nil {
			apiError(w, err)
			return true
		}
		write(w, 200, map[string]bool{"ok": true})
	case r.Method == "POST" && path == "/v1/manage/maintenance":
		var in MaintenanceInput
		if decode(raw, &in) != nil {
			apiError(w, ErrInvalid)
			return true
		}
		if err := s.store.SaveMaintenance(v, in); err != nil {
			apiError(w, err)
			return true
		}
		write(w, 200, map[string]bool{"ok": true})
	case r.Method == "PUT" && path == "/v1/manage/incidents/publication":
		var in struct {
			ID       string `json:"id"`
			Revision int64  `json:"revision"`
			Summary  string `json:"summary"`
			Enabled  bool   `json:"enabled"`
		}
		if decode(raw, &in) != nil {
			apiError(w, ErrInvalid)
			return true
		}
		if err := s.store.PublishIncident(v, in.ID, in.Revision, in.Summary, in.Enabled); err != nil {
			apiError(w, err)
			return true
		}
		write(w, 200, map[string]bool{"ok": true})
	case r.Method == "POST" && path == "/v1/manage/cleanup":
		if err := s.store.Cleanup(time.Now()); err != nil {
			apiError(w, err)
			return true
		}
		write(w, 200, map[string]bool{"ok": true})
	default:
		return false
	}
	return true
}
