package status

import (
	"database/sql"
	"encoding/json"
	"sort"
	"strings"
)

type timeWindow struct{ start, end int64 }
type stateEvidence struct {
	at, until int64
	state     string
}
type timelineControl struct {
	at             int64
	action, target string
}
type observationState struct {
	Version    int    `json:"version"`
	State      string `json:"state"`
	FreshUntil int64  `json:"fresh_until"`
}
type recordedMeasurements struct {
	Measurements
	State observationState `json:"_status"`
}

func mergeWindows(windows []timeWindow) []timeWindow {
	sort.Slice(windows, func(i, j int) bool { return windows[i].start < windows[j].start })
	out := []timeWindow{}
	for _, w := range windows {
		if w.end <= w.start {
			continue
		}
		if len(out) > 0 && w.start <= out[len(out)-1].end {
			out[len(out)-1].end = max(out[len(out)-1].end, w.end)
		} else {
			out = append(out, w)
		}
	}
	return out
}
func windowsAndResets(controls []timelineControl, maintenance []timeWindow, monitor string, until int64) ([]timeWindow, []int64) {
	paused := map[string]bool{}
	windows := append([]timeWindow{}, maintenance...)
	resets := []int64{}
	for _, w := range maintenance {
		resets = append(resets, w.end)
	}
	start := int64(0)
	active := false
	for _, c := range controls {
		if c.action == "monitor.reset" && c.target != monitor {
			continue
		}
		if strings.HasPrefix(c.action, "monitor.") && c.target != monitor {
			continue
		}
		resets = append(resets, c.at)
		if strings.HasSuffix(c.action, ".pause") {
			paused[c.target] = true
		} else if strings.HasSuffix(c.action, ".resume") {
			paused[c.target] = false
		} else {
			continue
		}
		nowActive := false
		for _, value := range paused {
			nowActive = nowActive || value
		}
		if !active && nowActive {
			start = c.at
		}
		if active && !nowActive {
			windows = append(windows, timeWindow{start, c.at})
		}
		active = nowActive
	}
	if active {
		windows = append(windows, timeWindow{start, until})
	}
	sort.Slice(resets, func(i, j int) bool { return resets[i] < resets[j] })
	return mergeWindows(windows), resets
}
func countTimeline(from, to int64, evidence []stateEvidence, windows []timeWindow, resets []int64) Uptime {
	out := Uptime{Version: 2}
	if from >= to {
		return out
	}
	sort.SliceStable(evidence, func(i, j int) bool { return evidence[i].at < evidence[j].at })
	points := []int64{from, to}
	add := func(at int64) {
		if at > from && at < to {
			points = append(points, at)
		}
	}
	for _, e := range evidence {
		add(e.at)
		add(e.until)
	}
	for _, w := range windows {
		add(w.start)
		add(w.end)
	}
	for _, at := range resets {
		add(at)
	}
	sort.Slice(points, func(i, j int) bool { return points[i] < points[j] })
	for i := 0; i < len(points)-1; i++ {
		start, end := points[i], points[i+1]
		if end <= start {
			continue
		}
		duration := end - start
		wi := sort.Search(len(windows), func(i int) bool { return windows[i].end > start })
		if wi < len(windows) && windows[wi].start <= start {
			out.ExcludedMS += duration
			continue
		}
		ei := sort.Search(len(evidence), func(i int) bool { return evidence[i].at > start }) - 1
		state := "unknown"
		if ei >= 0 && evidence[ei].until > start {
			state = evidence[ei].state
			ri := sort.Search(len(resets), func(i int) bool { return resets[i] > start }) - 1
			if ri >= 0 && resets[ri] >= evidence[ei].at {
				state = "unknown"
			}
		}
		switch state {
		case "operational":
			out.OperationalMS += duration
		case "outage":
			out.OutageMS += duration
		case "degraded":
			out.DegradedMS += duration
		default:
			out.UnknownMS += duration
		}
	}
	return out
}

type timelineQuerier interface {
	Query(string, ...any) (*sql.Rows, error)
}

func (s *Store) historyControls(component string, monitors []historyMonitor, to int64) ([]timelineControl, error) {
	return readHistoryControls(s.db, component, monitors, to)
}
func readHistoryControls(query timelineQuerier, component string, monitors []historyMonitor, to int64) ([]timelineControl, error) {
	args := []any{"service", component}
	for _, m := range monitors {
		args = append(args, m.id)
	}
	marks := strings.TrimSuffix(strings.Repeat("?,", len(args)), ",")
	args = append(args, to)
	rows, err := query.Query(`SELECT created_at,action,target_id FROM audit_events WHERE target_id IN (`+marks+`) AND action IN('probes.pause','probes.resume','component.pause','component.resume','component.save','monitor.pause','monitor.resume','monitor.reset') AND created_at<=? ORDER BY created_at,rowid LIMIT 10001`, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []timelineControl{}
	for rows.Next() {
		var c timelineControl
		if rows.Scan(&c.at, &c.action, &c.target) != nil {
			return nil, ErrInvalid
		}
		out = append(out, c)
		if len(out) > 10000 {
			return nil, ErrInvalid
		}
	}
	return out, rows.Err()
}
func (s *Store) historyEvidence(m historyMonitor, from, to int64) ([]stateEvidence, error) {
	return s.historyEvidenceLimit(m, from, to, 1000)
}
func (s *Store) historyEvidenceLimit(m historyMonitor, from, to int64, limit int) ([]stateEvidence, error) {
	out := []stateEvidence{}
	appendRaw := func(at int64, raw string) {
		var saved recordedMeasurements
		state := "unknown"
		until := at
		if json.Unmarshal([]byte(raw), &saved) == nil && saved.State.Version == 1 {
			state = saved.State.State
			until = saved.State.FreshUntil
		}
		out = append(out, stateEvidence{at, until, state})
	}
	var priorAt int64
	var priorRaw string
	err := s.db.QueryRow(`SELECT observed_at,measurements FROM observations WHERE monitor_id=? AND outcome<>'heartbeat' AND observed_at<? ORDER BY observed_at DESC,rowid DESC LIMIT 1`, m.id, from).Scan(&priorAt, &priorRaw)
	if err != nil && err != sql.ErrNoRows {
		return nil, err
	}
	if err == nil {
		appendRaw(priorAt, priorRaw)
	}
	rows, err := s.db.Query(`SELECT observed_at,measurements FROM observations WHERE monitor_id=? AND outcome<>'heartbeat' AND observed_at>=? AND observed_at<? ORDER BY observed_at,rowid LIMIT ?`, m.id, from, to, limit+1)
	if err != nil {
		return nil, err
	}
	count := 0
	for rows.Next() {
		var at int64
		var raw string
		if rows.Scan(&at, &raw) != nil {
			rows.Close()
			return nil, ErrInvalid
		}
		appendRaw(at, raw)
		count++
		if count > limit {
			rows.Close()
			return nil, ErrInvalid
		}
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return nil, err
	}
	if m.updated < to {
		out = append(out, stateEvidence{m.updated, m.freshUntil, m.state})
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].at < out[j].at })
	return out, nil
}

func clipEvidence(evidence []stateEvidence, from, to int64) []stateEvidence {
	start := sort.Search(len(evidence), func(i int) bool { return evidence[i].at >= from })
	end := sort.Search(len(evidence), func(i int) bool { return evidence[i].at >= to })
	return evidence[max(0, start-1):end]
}
