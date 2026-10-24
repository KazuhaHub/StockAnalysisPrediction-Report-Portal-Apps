package status

import (
	"sort"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

type historyMonitor struct {
	id, state                    string
	created, updated, freshUntil int64
}

func (s *Store) History(v protocol.Viewer, component string, from, to time.Time) ([]Uptime, error) {
	if !s.canRead(v, component, "read") {
		return nil, ErrNotFound
	}
	return s.computeHistory(component, from, to, nil)
}
func (s *Store) computeHistory(component string, from, to time.Time, collect func(int64, int64, Uptime)) ([]Uptime, error) {
	if !from.Before(to) || to.Sub(from) > 90*24*time.Hour || to.After(time.Now().Add(24*time.Hour)) {
		return nil, ErrInvalid
	}
	until := min(to.UnixMilli(), time.Now().UnixMilli())
	since := from.UnixMilli()
	if since >= until {
		return nil, ErrInvalid
	}
	rows, err := s.db.Query(`SELECT m.id,m.created_at,COALESCE(s.current_state,'unknown'),COALESCE(s.updated_at,m.created_at),COALESCE(o.observed_at,0),m.interval_seconds,m.timeout_seconds FROM monitors m LEFT JOIN monitor_states s ON s.monitor_id=m.id LEFT JOIN observations o ON o.id=s.last_observation_id WHERE m.component_id=? ORDER BY m.created_at,m.id LIMIT 101`, component)
	if err != nil {
		return nil, err
	}
	monitors := []historyMonitor{}
	for rows.Next() {
		var m historyMonitor
		var observed int64
		var interval, timeout int
		if rows.Scan(&m.id, &m.created, &m.state, &m.updated, &observed, &interval, &timeout) != nil {
			rows.Close()
			return nil, ErrInvalid
		}
		m.freshUntil = observed + int64(max(3*interval, 2*timeout))*1000
		if observed == 0 {
			m.freshUntil = m.updated
		}
		monitors = append(monitors, m)
		if len(monitors) > 100 {
			rows.Close()
			return nil, ErrInvalid
		}
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return nil, err
	}
	controls, err := s.historyControls(component, monitors, until)
	if err != nil {
		return nil, err
	}
	maintenance := []timeWindow{}
	corrections := []timeWindow{}
	rows, err = s.db.Query(`SELECT starts_at,ends_at,created_at FROM maintenance_windows WHERE component_id=? AND ends_at>? AND starts_at<? ORDER BY starts_at LIMIT 1001`, component, since-3*86400000, until)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var w timeWindow
		var created int64
		if rows.Scan(&w.start, &w.end, &created) != nil {
			rows.Close()
			return nil, ErrInvalid
		}
		maintenance = append(maintenance, w)
		if created > w.start {
			corrections = append(corrections, timeWindow{w.start, w.end + 3*86400000})
		}
		if len(maintenance) > 1000 {
			rows.Close()
			return nil, ErrInvalid
		}
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return nil, err
	}
	corrections = mergeWindows(corrections)
	aggregates := map[string]map[int64]Uptime{}
	floor := from.UTC().Truncate(time.Hour).UnixMilli()
	rows, err = s.db.Query(`SELECT a.monitor_id,a.hour_at,a.operational_ms,a.outage_ms,a.degraded_ms,a.excluded_ms FROM hourly_aggregates a JOIN monitors m ON m.id=a.monitor_id WHERE m.component_id=? AND a.hour_at>=? AND a.hour_at<? ORDER BY a.monitor_id,a.hour_at`, component, floor, until)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var id string
		var hour int64
		var totals Uptime
		if rows.Scan(&id, &hour, &totals.OperationalMS, &totals.OutageMS, &totals.DegradedMS, &totals.ExcludedMS) != nil {
			rows.Close()
			return nil, ErrInvalid
		}
		if aggregates[id] == nil {
			aggregates[id] = map[int64]Uptime{}
		}
		aggregates[id][hour] = totals
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return nil, err
	}
	out := []Uptime{}
	for _, m := range monitors {
		start := max(since, m.created)
		if start >= until {
			continue
		}
		windows, resets := windowsAndResets(controls, maintenance, m.id, until)
		var correctionEvidence []stateEvidence
		correctionIndex := sort.Search(len(corrections), func(i int) bool { return corrections[i].end > start })
		hasCorrections := correctionIndex < len(corrections) && corrections[correctionIndex].start < until
		if hasCorrections {
			correctionEvidence, err = s.historyEvidenceLimit(m, start, until, 600000)
			if err != nil {
				return nil, err
			}
		}
		totals := Uptime{MonitorID: m.id, Version: 2, SpanMS: until - start}
		for at := start; at < until; {
			hour := time.UnixMilli(at).UTC().Truncate(time.Hour).UnixMilli()
			end := min(until, hour+3600000)
			bucket := Uptime{}
			correction := sort.Search(len(corrections), func(i int) bool { return corrections[i].end > at })
			rebuild := correction < len(corrections) && corrections[correction].start < end
			if at != hour || end != hour+3600000 || rebuild {
				var evidence []stateEvidence
				if hasCorrections {
					evidence = clipEvidence(correctionEvidence, at, end)
				} else {
					evidence, err = s.historyEvidence(m, at, end)
					if err != nil {
						return nil, err
					}
				}
				bucket = countTimeline(at, end, evidence, windows, resets)
			} else {
				bucket = aggregates[m.id][hour]
				tailStart := max(at, m.updated)
				if tailStart < end {
					tail := countTimeline(tailStart, end, []stateEvidence{{m.updated, m.freshUntil, m.state}}, windows, resets)
					bucket.OperationalMS += tail.OperationalMS
					bucket.OutageMS += tail.OutageMS
					bucket.DegradedMS += tail.DegradedMS
					bucket.ExcludedMS += tail.ExcludedMS
				}
				known := bucket.OperationalMS + bucket.OutageMS + bucket.DegradedMS + bucket.ExcludedMS
				if known < 0 || known > end-at {
					return nil, ErrInvalid
				}
				bucket.UnknownMS = end - at - known
			}
			if collect != nil {
				collect(at, end, bucket)
			}
			totals.OperationalMS += bucket.OperationalMS
			totals.OutageMS += bucket.OutageMS
			totals.DegradedMS += bucket.DegradedMS
			totals.UnknownMS += bucket.UnknownMS
			totals.ExcludedMS += bucket.ExcludedMS
			at = end
		}
		totals.EligibleMS = totals.OperationalMS + totals.OutageMS + totals.DegradedMS
		totals.ObservedMS = totals.EligibleMS
		totals.CoverageMS = totals.ObservedMS
		if totals.EligibleMS+totals.UnknownMS+totals.ExcludedMS != totals.SpanMS {
			return nil, ErrInvalid
		}
		out = append(out, totals)
	}
	return out, nil
}
