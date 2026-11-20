package main

import (
	"errors"
	"math"
	"net/http"
	"net/url"
	"sort"
	"strconv"
	"strings"
)

// History routes (docs/store-v2.md), margin, panorama and etf only; risk and
// sentiment have no history and answer 404. Everything is answered from the
// parquet history files, never from snapshots.
//
//	/v1/{m}/history/dates
//	/v1/{m}/history?code=&fields=&from=&to=
//	/v1/{m}/compare?from=&to=&fields=&changed=&page=&size=
//	/v1/{m}/streak?field=&op=&value=&days=&date=&page=&size=
//	/v1/{m}/counts?field=&from=&to=
//
// Statuses beyond the existing routes' (400 bad_request, 404 not_found, 409
// unavailable): 404 no_data for a date that is not a history date, 429 busy
// while another history query runs, 409 query_timeout past the 4 s deadline.
// Series (history, counts) are returned oldest first, so a chart can plot
// them as they come; when a window is cut at its cap, truncated is true and
// next_to is the newest date not returned, to page further back with to=.

const (
	maxHistoryFields = 8
	maxHistoryDates  = 250
	maxCountsDates   = 500
	maxCompareSize   = 100
	maxStreakSize    = 200
	maxStreakDays    = 60
	defaultPageSize  = 50
)

// countFields is the allowlist of categorical fields counts accepts.
var countFields = map[string][]string{
	"margin":   {"state", "level"},
	"panorama": {"label", "quad", "profile", "sw1"},
	"etf":      {"cat"},
}

func (s *server) history(w http.ResponseWriter, r *http.Request, module string, parts []string, query url.Values) {
	if !historyModules[module] {
		writeError(w, http.StatusNotFound, "not_found")
		return
	}
	if len(parts) == 3 && parts[1] == "history" && parts[2] == "dates" {
		if r.URL.RawQuery != "" {
			writeError(w, http.StatusBadRequest, "bad_request")
			return
		}
		dates, err := s.store.HistoryDates(module)
		if err != nil {
			writeError(w, http.StatusConflict, "unavailable")
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"module": module, "dates": dates})
		return
	}
	if len(parts) != 2 {
		writeError(w, http.StatusBadRequest, "bad_request")
		return
	}
	params, ok := singleValues(query)
	if !ok {
		writeError(w, http.StatusBadRequest, "bad_request")
		return
	}
	var (
		result any
		err    error
	)
	bad := func() { writeError(w, http.StatusBadRequest, "bad_request") }
	switch parts[1] {
	case "history":
		p, ok := parseHistoryParams(module, params)
		if !ok {
			bad()
			return
		}
		result, err = s.store.queryHistory(module, p)
	case "compare":
		p, ok := parseCompareParams(module, params)
		if !ok {
			bad()
			return
		}
		result, err = s.store.queryCompare(module, p)
	case "streak":
		p, ok := parseStreakParams(module, params)
		if !ok {
			bad()
			return
		}
		result, err = s.store.queryStreak(module, p)
	case "counts":
		p, ok := parseCountsParams(module, params)
		if !ok {
			bad()
			return
		}
		result, err = s.store.queryCounts(module, p)
	default:
		bad()
		return
	}
	switch {
	case errors.Is(err, errBusy):
		writeError(w, http.StatusTooManyRequests, "busy")
	case errors.Is(err, errTimeout):
		writeError(w, http.StatusConflict, "query_timeout")
	case errors.Is(err, errNotFound):
		writeError(w, http.StatusNotFound, "no_data")
	case err != nil:
		writeError(w, http.StatusConflict, "unavailable")
	default:
		writeJSON(w, http.StatusOK, result)
	}
}

// singleValues flattens a query to one value per key; a repeated key is refused.
func singleValues(q url.Values) (map[string]string, bool) {
	out := make(map[string]string, len(q))
	for k, v := range q {
		if len(v) != 1 {
			return nil, false
		}
		out[k] = v[0]
	}
	return out, true
}

// only reports whether params has no key outside allowed.
func only(params map[string]string, allowed ...string) bool {
	for k := range params {
		found := false
		for _, a := range allowed {
			found = found || k == a
		}
		if !found {
			return false
		}
	}
	return true
}

// parseFieldList reads the fields parameter: absent is allowed unless
// required, but a present one must be a non-empty list of distinct columns.
func parseFieldList(module string, params map[string]string, required bool) ([]string, bool) {
	value, present := params["fields"]
	if !present {
		return nil, !required
	}
	if value == "" {
		return nil, false
	}
	fields := strings.Split(value, ",")
	if len(fields) > maxHistoryFields {
		return nil, false
	}
	seen := map[string]bool{}
	for _, f := range fields {
		if _, _, ok := historyColumn(module, f); !ok || seen[f] {
			return nil, false
		}
		seen[f] = true
	}
	return fields, true
}

func optionalDate(params map[string]string, key string) (string, bool) {
	v, present := params[key]
	if !present {
		return "", true
	}
	return v, validDate(v)
}

func parsePositive(params map[string]string, key string, def, max int) (int, bool) {
	v, present := params[key]
	if !present {
		return def, true
	}
	n, err := strconv.Atoi(v)
	return n, err == nil && n >= 1 && n <= max
}

type historyParams struct {
	code     string
	fields   []string
	from, to string
}

func parseHistoryParams(module string, params map[string]string) (historyParams, bool) {
	var p historyParams
	var ok bool
	if !only(params, "code", "fields", "from", "to") {
		return p, false
	}
	p.code = params["code"]
	if p.code == "" || len(p.code) > maxCodeLength {
		return p, false
	}
	if p.fields, ok = parseFieldList(module, params, true); !ok {
		return p, false
	}
	if p.from, ok = optionalDate(params, "from"); !ok {
		return p, false
	}
	if p.to, ok = optionalDate(params, "to"); !ok {
		return p, false
	}
	return p, p.from == "" || p.to == "" || p.from <= p.to
}

type compareParams struct {
	from, to, changed string
	fields            []string
	page, size        int
}

func parseCompareParams(module string, params map[string]string) (compareParams, bool) {
	var p compareParams
	var ok bool
	if !only(params, "from", "to", "fields", "changed", "page", "size") {
		return p, false
	}
	p.from, p.to = params["from"], params["to"]
	if !validDate(p.from) || !validDate(p.to) {
		return p, false
	}
	if p.fields, ok = parseFieldList(module, params, false); !ok {
		return p, false
	}
	if p.changed = params["changed"]; p.changed != "" {
		col, _, known := historyColumn(module, p.changed)
		if !known || !col.str || p.changed == "tags" {
			return p, false
		}
	} else if _, present := params["changed"]; present {
		return p, false
	}
	if p.page, ok = parsePositive(params, "page", 1, 1_000_000); !ok {
		return p, false
	}
	p.size, ok = parsePositive(params, "size", defaultPageSize, maxCompareSize)
	return p, ok
}

type streakParams struct {
	field, op, date string
	text            string
	number          float64
	days            int
	page, size      int
}

func parseStreakParams(module string, params map[string]string) (streakParams, bool) {
	var p streakParams
	var ok bool
	if !only(params, "field", "op", "value", "days", "date", "page", "size") {
		return p, false
	}
	p.field, p.op = params["field"], params["op"]
	col, _, known := historyColumn(module, p.field)
	if !known {
		return p, false
	}
	value, present := params["value"]
	if !present {
		return p, false
	}
	if col.str {
		if p.field == "tags" || p.op != "eq" || len(value) > 64 {
			return p, false
		}
		p.text = value
	} else {
		if p.op != "eq" && p.op != "gte" && p.op != "lte" {
			return p, false
		}
		n, err := strconv.ParseFloat(value, 64)
		if err != nil || math.IsNaN(n) || math.IsInf(n, 0) {
			return p, false
		}
		p.number = n
	}
	if p.days, ok = parsePositive(params, "days", 0, maxStreakDays); !ok || p.days == 0 {
		return p, false
	}
	if p.date, ok = optionalDate(params, "date"); !ok {
		return p, false
	}
	if p.page, ok = parsePositive(params, "page", 1, 1_000_000); !ok {
		return p, false
	}
	p.size, ok = parsePositive(params, "size", defaultPageSize, maxStreakSize)
	return p, ok
}

type countsParams struct {
	field, from, to string
}

func parseCountsParams(module string, params map[string]string) (countsParams, bool) {
	var p countsParams
	var ok bool
	if !only(params, "field", "from", "to") {
		return p, false
	}
	p.field = params["field"]
	allowed := false
	for _, f := range countFields[module] {
		allowed = allowed || f == p.field
	}
	if !allowed {
		return p, false
	}
	if p.from, ok = optionalDate(params, "from"); !ok {
		return p, false
	}
	if p.to, ok = optionalDate(params, "to"); !ok {
		return p, false
	}
	return p, p.from == "" || p.to == "" || p.from <= p.to
}

// window picks the history dates in [from, to] (either may be empty) and
// keeps the newest limit of them. It returns them newest first, whether the
// range had more, and the newest date left out.
func window(all []string, from, to string, limit int) (picked []string, truncated bool, nextTo string) {
	var inRange []string
	for _, d := range all { // all is newest first
		if (from == "" || d >= from) && (to == "" || d <= to) {
			inRange = append(inRange, d)
		}
	}
	if len(inRange) > limit {
		return inRange[:limit], true, inRange[limit]
	}
	return inRange, false, ""
}

func reversed(in []string) []string {
	out := make([]string, len(in))
	for i, d := range in {
		out[len(in)-1-i] = d
	}
	return out
}

// value reads one cell as a JSON value: nil, a string or a float64.
func (v *histView) value(col string, i int) any {
	c := v.cols[col]
	if !c.ok[i] {
		return nil
	}
	if c.str != nil {
		return c.str[i]
	}
	return c.num[i]
}

func (v *histView) rowOf(code string) (int, bool) {
	for i, c := range v.cols["code"].str {
		if c == code {
			return i, true
		}
	}
	return 0, false
}

func (s *Store) queryHistory(module string, p historyParams) (any, error) {
	q, done, err := s.beginHistory()
	if err != nil {
		return nil, err
	}
	defer done()
	all, err := s.HistoryDates(module)
	if err != nil {
		return nil, err
	}
	picked, truncated, nextTo := window(all, p.from, p.to, maxHistoryDates)
	q.planScan(len(picked))
	items := []map[string]any{}
	for _, date := range picked { // newest first; reversed below
		view, err := q.load(module, date, p.fields...)
		if err != nil {
			return nil, err
		}
		i, found := view.rowOf(p.code)
		if !found {
			continue // dates without the code are omitted
		}
		item := map[string]any{"date": date}
		for _, f := range p.fields {
			item[f] = view.value(f, i)
		}
		items = append(items, item)
	}
	for i, j := 0, len(items)-1; i < j; i, j = i+1, j-1 {
		items[i], items[j] = items[j], items[i]
	}
	out := map[string]any{"module": module, "code": p.code, "fields": p.fields, "items": items, "truncated": truncated}
	if truncated {
		out["next_to"] = nextTo
	}
	return out, nil
}

func (s *Store) queryCompare(module string, p compareParams) (any, error) {
	q, done, err := s.beginHistory()
	if err != nil {
		return nil, err
	}
	defer done()
	q.planScan(2)
	names := append([]string{"name"}, p.fields...)
	if p.changed != "" {
		names = append(names, p.changed)
	}
	from, err := q.load(module, p.from, names...)
	if err != nil {
		return nil, err
	}
	to, err := q.load(module, p.to, names...)
	if err != nil {
		return nil, err
	}
	fromRow, toRow := map[string]int{}, map[string]int{}
	codes := make([]string, 0, from.rows+to.rows)
	for i := 0; i < from.rows; i++ {
		fromRow[from.code(i)] = i
		codes = append(codes, from.code(i))
	}
	for i := 0; i < to.rows; i++ {
		toRow[to.code(i)] = i
		if _, both := fromRow[to.code(i)]; !both {
			codes = append(codes, to.code(i))
		}
	}
	sort.Strings(codes)
	side := func(v *histView, rows map[string]int, code string) (map[string]any, int) {
		i, ok := rows[code]
		if !ok {
			return nil, -1
		}
		vals := map[string]any{}
		for _, f := range p.fields {
			vals[f] = v.value(f, i)
		}
		return vals, i
	}
	matched := make([]string, 0, len(codes))
	for _, code := range codes {
		if p.changed != "" {
			fi, inFrom := fromRow[code]
			ti, inTo := toRow[code]
			// A code on one side only is changed: absent is not a null value.
			// Present on both, a null differs from a value, two nulls do not.
			if inFrom && inTo && from.value(p.changed, fi) == to.value(p.changed, ti) {
				continue
			}
		}
		matched = append(matched, code)
	}
	start := (p.page - 1) * p.size
	items := []map[string]any{}
	for k := start; k < len(matched) && k < start+p.size; k++ {
		code := matched[k]
		fromVals, fi := side(from, fromRow, code)
		toVals, ti := side(to, toRow, code)
		var name any
		switch {
		case ti >= 0:
			name = to.value("name", ti)
		case fi >= 0:
			name = from.value("name", fi)
		}
		item := map[string]any{"code": code, "name": name, "from": fromVals, "to": toVals}
		diff := map[string]any{}
		for _, f := range p.fields {
			if col, _, _ := historyColumn(module, f); col.str {
				continue
			}
			var d any
			if fromVals != nil && toVals != nil {
				a, aok := fromVals[f].(float64)
				b, bok := toVals[f].(float64)
				if aok && bok {
					d = b - a
				}
			}
			diff[f] = d
		}
		item["diff"] = diff // always an object, empty without numeric fields
		items = append(items, item)
	}
	return map[string]any{"module": module, "from": p.from, "to": p.to, "fields": nonNil(p.fields),
		"page": p.page, "size": p.size, "total": len(matched), "items": items}, nil
}

func nonNil(in []string) []string {
	if in == nil {
		return []string{}
	}
	return in
}

func (s *Store) queryStreak(module string, p streakParams) (any, error) {
	q, done, err := s.beginHistory()
	if err != nil {
		return nil, err
	}
	defer done()
	all, err := s.HistoryDates(module)
	if err != nil {
		return nil, err
	}
	start := 0
	if p.date != "" {
		start = -1
		for i, d := range all {
			if d == p.date {
				start = i
			}
		}
		if start < 0 {
			return nil, errNotFound
		}
	} else if len(all) == 0 {
		return nil, errNotFound
	}
	used := all[start:min(start+p.days, len(all))]
	q.planScan(len(used))
	col, _, _ := historyColumn(module, p.field)
	meets := func(v *histView, i int) bool {
		if !v.cols[p.field].ok[i] {
			return false // null fails the condition
		}
		if col.str {
			return v.cols[p.field].str[i] == p.text
		}
		x := v.cols[p.field].num[i]
		switch p.op {
		case "gte":
			return x >= p.number
		case "lte":
			return x <= p.number
		}
		return x == p.number
	}
	names := map[string]any{} // code -> name on the newest date (nil when null)
	complete := len(used) == p.days
	if complete {
		for n, date := range used { // newest first
			view, err := q.load(module, date, "name", p.field)
			if err != nil {
				return nil, err
			}
			keep := map[string]bool{}
			for i := 0; i < view.rows; i++ {
				code := view.code(i)
				if n > 0 {
					if _, still := names[code]; !still {
						continue
					}
				}
				if meets(view, i) {
					keep[code] = true
					if n == 0 {
						names[code] = view.value("name", i)
					}
				}
			}
			for code := range names {
				if !keep[code] {
					delete(names, code)
				}
			}
			if len(names) == 0 {
				break
			}
		}
	}
	codes := make([]string, 0, len(names))
	for code := range names {
		codes = append(codes, code)
	}
	sort.Strings(codes)
	from := (p.page - 1) * p.size
	items := []map[string]any{}
	for k := from; k < len(codes) && k < from+p.size; k++ {
		items = append(items, map[string]any{"code": codes[k], "name": names[codes[k]]})
	}
	return map[string]any{"module": module, "field": p.field, "op": p.op, "days": p.days, "complete": complete,
		"dates": used, "page": p.page, "size": p.size, "total": len(codes), "items": items}, nil
}

func (s *Store) queryCounts(module string, p countsParams) (any, error) {
	q, done, err := s.beginHistory()
	if err != nil {
		return nil, err
	}
	defer done()
	all, err := s.HistoryDates(module)
	if err != nil {
		return nil, err
	}
	picked, truncated, nextTo := window(all, p.from, p.to, maxCountsDates)
	q.planScan(len(picked))
	items := []map[string]any{}
	for _, date := range reversed(picked) {
		view, err := q.load(module, date, p.field)
		if err != nil {
			return nil, err
		}
		// Nulls are reported apart from the values, so a value that is
		// literally the text "null" cannot collide with them.
		counts, nulls := map[string]int{}, 0
		for i := 0; i < view.rows; i++ {
			if v, ok := view.str(p.field, i); ok {
				counts[v]++
			} else {
				nulls++
			}
		}
		items = append(items, map[string]any{"date": date, "counts": counts, "nulls": nulls})
	}
	out := map[string]any{"module": module, "field": p.field, "items": items, "truncated": truncated}
	if truncated {
		out["next_to"] = nextTo
	}
	return out, nil
}
