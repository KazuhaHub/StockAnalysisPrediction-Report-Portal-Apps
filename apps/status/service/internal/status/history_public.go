package status

import (
	"sort"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

type HourlyState struct {
	From  string `json:"from"`
	To    string `json:"to"`
	State string `json:"state"`
}

func (s *Store) HourlyHistory(v protocol.Viewer, component string, from, to time.Time) ([]HourlyState, error) {
	if !s.canRead(v, component, "read") {
		return nil, ErrNotFound
	}
	return s.coarseHistory(component, from, to)
}
func (s *Store) PublicHistory(component string, from, to time.Time) ([]HourlyState, error) {
	if s.setting("public_enabled") != "1" {
		return nil, ErrNotFound
	}
	var enabled int
	if err := s.db.QueryRow(`SELECT COUNT(*) FROM components WHERE id=? AND enabled=1 AND public_enabled=1`, component).Scan(&enabled); err != nil {
		return nil, err
	}
	if enabled != 1 {
		return nil, ErrNotFound
	}
	return s.coarseHistory(component, from, to)
}
func (s *Store) coarseHistory(component string, from, to time.Time) ([]HourlyState, error) {
	type bucket struct {
		start, end int64
		state      string
	}
	buckets := map[int64]bucket{}
	priority := map[string]int{"operational": 1, "unknown": 2, "degraded": 3, "outage": 4}
	_, err := s.computeHistory(component, from, to, func(start, end int64, totals Uptime) {
		state := "operational"
		switch {
		case totals.OutageMS > 0:
			state = "outage"
		case totals.DegradedMS > 0:
			state = "degraded"
		case totals.UnknownMS > 0 || totals.ExcludedMS > 0:
			state = "unknown"
		}
		hour := time.UnixMilli(start).UTC().Truncate(time.Hour).UnixMilli()
		old, exists := buckets[hour]
		if !exists {
			buckets[hour] = bucket{start, end, state}
			return
		}
		if priority[state] > priority[old.state] {
			old.state = state
		}
		old.start = min(old.start, start)
		old.end = max(old.end, end)
		buckets[hour] = old
	})
	if err != nil {
		return nil, err
	}
	hours := make([]int64, 0, len(buckets))
	for hour := range buckets {
		hours = append(hours, hour)
	}
	sort.Slice(hours, func(i, j int) bool { return hours[i] < hours[j] })
	out := make([]HourlyState, 0, len(hours))
	for _, hour := range hours {
		b := buckets[hour]
		out = append(out, HourlyState{From: utc(b.start), To: utc(b.end), State: b.state})
	}
	return out, nil
}
