package status

import (
	"encoding/json"
	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
	"time"
)

type ComponentPage struct {
	Items  []ComponentView `json:"items"`
	Total  int             `json:"total"`
	Offset int             `json:"offset"`
	Limit  int             `json:"limit"`
}

func (s *Store) ComponentPage(v protocol.Viewer, now time.Time, offset, limit int, search string) (ComponentPage, error) {
	page := ComponentPage{Items: []ComponentView{}, Offset: offset, Limit: limit}
	if offset < 0 || offset > 1000000 || limit < 1 || limit > 100 || len(search) > 120 {
		return page, ErrInvalid
	}
	filter, args := componentFilter(v, "c", false)
	if search != "" {
		filter += " AND instr(lower(c.label),lower(?))>0"
		args = append(args, search)
	}
	if err := s.db.QueryRow(`SELECT COUNT(*) FROM components c WHERE c.enabled=1 AND `+filter, args...).Scan(&page.Total); err != nil {
		return page, err
	}
	var err error
	page.Items, err = s.componentRange(v, false, now, "", search, offset, limit)
	return page, err
}
func (s *Store) Component(v protocol.Viewer, id string, now time.Time) (ComponentView, error) {
	if id == "" || len(id) > 64 {
		return ComponentView{}, ErrNotFound
	}
	views, err := s.componentRange(v, false, now, id, "", 0, 1)
	if err != nil {
		return ComponentView{}, err
	}
	if len(views) != 1 {
		return ComponentView{}, ErrNotFound
	}
	return views[0], nil
}

type ComponentExport struct {
	Version     int           `json:"version"`
	GeneratedAt string        `json:"generated_at"`
	From        string        `json:"from"`
	To          string        `json:"to"`
	Component   ComponentView `json:"component"`
	Uptime      []Uptime      `json:"uptime"`
	Hourly      []HourlyState `json:"hourly"`
}

func (s *Store) ExportComponent(v protocol.Viewer, id string, from, to time.Time) (ComponentExport, error) {
	result := ComponentExport{Version: 1, GeneratedAt: utc(time.Now().UnixMilli()), From: utc(from.UnixMilli()), To: utc(to.UnixMilli())}
	var err error
	result.Component, err = s.Component(v, id, time.Now())
	if err != nil {
		return ComponentExport{}, err
	}
	result.Uptime, err = s.History(v, id, from, to)
	if err != nil {
		return ComponentExport{}, err
	}
	result.Hourly, err = s.HourlyHistory(v, id, from, to)
	if err != nil {
		return ComponentExport{}, err
	}
	raw, err := json.Marshal(result)
	if err != nil || len(raw) > 512*1024 {
		return ComponentExport{}, ErrInvalid
	}
	return result, nil
}
