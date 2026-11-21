package main

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

// putHistory writes a history file straight into the store, without a
// snapshot: the history queries never read snapshots.
func putHistory(t testing.TB, s *Store, module, date string, rows []map[string]any) {
	t.Helper()
	dir := filepath.Join(s.histRoot, module)
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	putHistoryFile(t, filepath.Join(dir, date+historySuffix),
		historyFile(t, histSpec{module: module, asOf: date, rows: rows}))
}

func mrow(code, name string, price, frag any, state any) map[string]any {
	return map[string]any{"code": code, "name": name, "price": price, "frag": frag, "state": state, "level": "高", "tags": "t"}
}

// historyEnv has a margin history of five days with a gap (no file for
// 2026-11-11): codes appear (000004 from the 12th) and disappear (688001
// after the 10th), values are null on some days.
func historyEnv(t *testing.T) testEnv {
	e := newBareEnv(t)
	s := e.srv.store
	days := map[string][]map[string]any{
		"2026-11-10": {
			mrow("600000", "A", 10.0, 90.0, "临界"), mrow("000001", "B", 9.0, 30.0, "安全"),
			mrow("300001", "C", nil, 50.0, "潜伏"), mrow("688001", "E", 20.0, 5.0, "安全")},
		"2026-11-12": {
			mrow("600000", "A", 11.0, 91.0, "临界"), mrow("000001", "B", 9.5, 31.0, "临界"),
			mrow("300001", "C", 8.0, 52.0, "临界"), mrow("000004", "D", 5.0, 10.0, "安全")},
		"2026-11-13": {
			mrow("600000", "A", 12.0, 92.0, "临界"), mrow("000001", "B", 9.0, 33.0, "临界"),
			mrow("300001", "C", 7.0, nil, "临界"), mrow("000004", "D", 5.5, 11.0, "安全")},
		"2026-11-14": {
			mrow("600000", "A", 12.0, 95.0, "临界"), mrow("000001", "B", 9.0, 35.0, "临界"),
			mrow("300001", "C", 7.0, 55.0, "临界"), mrow("000004", "D", 5.5, 12.0, nil)},
	}
	for date, rows := range days {
		putHistory(t, s, "margin", date, rows)
	}
	return e
}

func (e testEnv) getJSON(t *testing.T, path string, status int) map[string]any {
	t.Helper()
	rec := e.get(t, path, true)
	if rec.Code != status {
		t.Fatalf("%s: %d %s, want %d", path, rec.Code, rec.Body.String(), status)
	}
	return decode(t, rec)
}

func items(t *testing.T, out map[string]any) []map[string]any {
	t.Helper()
	raw, _ := out["items"].([]any)
	list := make([]map[string]any, len(raw))
	for i, r := range raw {
		list[i] = r.(map[string]any)
	}
	return list
}

func codesOf(list []map[string]any) string {
	codes := make([]string, len(list))
	for i, it := range list {
		codes[i] = it["code"].(string)
	}
	return strings.Join(codes, ",")
}

func TestReadyReportsDataFormat2(t *testing.T) {
	e := newBareEnv(t)
	req := httptest.NewRequest(http.MethodGet, "http://portal-app.invalid/health/ready", nil)
	rec := httptest.NewRecorder()
	e.srv.ServeHTTP(rec, req)
	if out := decode(t, rec); out["data_format"] != "2" {
		t.Fatalf("%v", out)
	}
}

func TestHistoryRoutesAreForRowModulesOnly(t *testing.T) {
	e := historyEnv(t)
	for _, module := range []string{"risk", "sentiment"} {
		for _, path := range []string{"/history/dates", "/history?code=1&fields=price", "/compare?from=2026-11-10&to=2026-11-12",
			"/streak?field=state&op=eq&value=x&days=1", "/counts?field=state"} {
			if rec := e.get(t, "/v1/"+module+path, true); rec.Code != http.StatusNotFound {
				t.Errorf("%s%s: %d", module, path, rec.Code)
			}
		}
	}
	if rec := e.get(t, "/v1/bogus/history/dates", true); rec.Code != http.StatusNotFound {
		t.Errorf("unknown module %d", rec.Code)
	}
	if rec := e.get(t, "/v1/margin/history/dates", false); rec.Code != http.StatusForbidden {
		t.Errorf("unsigned %d", rec.Code)
	}
}

func TestHistoryDatesNewestFirst(t *testing.T) {
	e := historyEnv(t)
	out := e.getJSON(t, "/v1/margin/history/dates", 200)
	got := fmt.Sprint(out["dates"])
	if got != "[2026-11-14 2026-11-13 2026-11-12 2026-11-10]" {
		t.Fatalf("dates %s", got)
	}
	if out := e.getJSON(t, "/v1/etf/history/dates", 200); fmt.Sprint(out["dates"]) != "[]" {
		t.Fatalf("empty module %v", out)
	}
	e.getJSON(t, "/v1/margin/history/dates?x=1", 400)
	e.getJSON(t, "/v1/margin/history/other", 400)
}

func TestHistoryOfOneCode(t *testing.T) {
	e := historyEnv(t)
	out := e.getJSON(t, "/v1/margin/history?code=300001&fields=price,state,frag", 200)
	list := items(t, out)
	if len(list) != 4 || list[0]["date"] != "2026-11-10" || list[3]["date"] != "2026-11-14" {
		t.Fatalf("oldest first: %v", list)
	}
	if list[0]["price"] != nil || list[0]["state"] != "潜伏" || list[2]["frag"] != nil || list[1]["price"] != 8.0 {
		t.Fatalf("values/nulls %v", list)
	}
	if out["truncated"] != false {
		t.Fatal("truncated")
	}
	// Dates without the code are omitted: 000004 starts on the 12th, 688001 ends on the 10th.
	if got := items(t, e.getJSON(t, "/v1/margin/history?code=000004&fields=name", 200)); len(got) != 3 || got[0]["date"] != "2026-11-12" {
		t.Fatalf("appearing code %v", got)
	}
	if got := items(t, e.getJSON(t, "/v1/margin/history?code=688001&fields=name", 200)); len(got) != 1 || got[0]["date"] != "2026-11-10" {
		t.Fatalf("disappearing code %v", got)
	}
	if got := items(t, e.getJSON(t, "/v1/margin/history?code=999999&fields=name", 200)); len(got) != 0 {
		t.Fatalf("unknown code %v", got)
	}
	// from and to bound the window, inclusive; the gap day has no file.
	out = e.getJSON(t, "/v1/margin/history?code=600000&fields=price&from=2026-11-11&to=2026-11-13", 200)
	if list := items(t, out); len(list) != 2 || list[0]["date"] != "2026-11-12" || list[1]["date"] != "2026-11-13" {
		t.Fatalf("window %v", list)
	}
	// A date outside the history is a valid bound, not an error.
	if got := items(t, e.getJSON(t, "/v1/margin/history?code=600000&fields=price&to=2020-01-01", 200)); len(got) != 0 {
		t.Fatalf("before the history %v", got)
	}
}

func TestHistoryRefusals(t *testing.T) {
	e := historyEnv(t)
	nine := "price,chg,rz,ratio,dratio20,rz_chg5,rz_chg20,buf_call,buf_liq"
	bad := []string{
		"", "?fields=price", "?code=1", "?code=&fields=price",
		"?code=" + strings.Repeat("1", 17) + "&fields=price",
		"?code=1&fields=" + nine,
		"?code=1&fields=price,price",
		"?code=1&fields=price,",
		"?code=1&fields=nope",
		"?code=1&fields=res_detail",   // a snapshot field outside the history schema
		"?code=1&fields=py",           // likewise
		"?code=1&fields=Price",        // case matters
		"?code=1&fields=../x",         // not a column name
		"?code=1&fields=price&from=x", // bad date
		"?code=1&fields=price&to=2026-02-30",
		"?code=1&fields=price&from=2026-11-13&to=2026-11-12",
		"?code=1&fields=price&extra=1",
		"?code=1&code=2&fields=price",
		"?code=1&fields=price&fields=chg",
	}
	for _, q := range bad {
		if rec := e.get(t, "/v1/margin/history"+q, true); rec.Code != http.StatusBadRequest {
			t.Errorf("%q: %d", q, rec.Code)
		}
	}
	// Eight fields are allowed.
	e.getJSON(t, "/v1/margin/history?code=600000&fields="+strings.TrimSuffix(nine, ",buf_liq"), 200)
}

func TestHistoryCapsAtTwoHundredFiftyDatesAndPagesBackWithTo(t *testing.T) {
	e := newBareEnv(t)
	start := time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC)
	for i := 0; i < 300; i++ {
		putHistory(t, e.srv.store, "etf", start.AddDate(0, 0, i).Format("2006-01-02"),
			[]map[string]any{{"code": "588000", "name": "X", "cum20": float64(i)}})
	}
	out := e.getJSON(t, "/v1/etf/history?code=588000&fields=cum20", 200)
	list := items(t, out)
	if len(list) != 250 || out["truncated"] != true {
		t.Fatalf("%d items, truncated %v", len(list), out["truncated"])
	}
	// The newest 250, oldest first: day 299 is last.
	if list[249]["cum20"] != 299.0 || list[0]["cum20"] != 50.0 {
		t.Fatalf("window %v .. %v", list[0], list[249])
	}
	next, _ := out["next_to"].(string)
	if next != start.AddDate(0, 0, 49).Format("2006-01-02") {
		t.Fatalf("next_to %q", next)
	}
	out = e.getJSON(t, "/v1/etf/history?code=588000&fields=cum20&to="+next, 200)
	list = items(t, out)
	if len(list) != 50 || out["truncated"] != false || list[0]["cum20"] != 0.0 {
		t.Fatalf("second page %d %v", len(list), out["truncated"])
	}
	if _, ok := out["next_to"]; ok {
		t.Fatal("next_to on a complete window")
	}
}

func TestCompareJoinsOnCodeAndOrdersByCode(t *testing.T) {
	e := historyEnv(t)
	out := e.getJSON(t, "/v1/margin/compare?from=2026-11-10&to=2026-11-14&fields=price,state", 200)
	list := items(t, out)
	if codesOf(list) != "000001,000004,300001,600000,688001" || out["total"] != 5.0 {
		t.Fatalf("full outer join: %s total %v", codesOf(list), out["total"])
	}
	byCode := map[string]map[string]any{}
	for _, it := range list {
		byCode[it["code"].(string)] = it
	}
	a := byCode["600000"]
	from, to, diff := a["from"].(map[string]any), a["to"].(map[string]any), a["diff"].(map[string]any)
	if from["price"] != 10.0 || to["price"] != 12.0 || diff["price"] != 2.0 || a["name"] != "A" {
		t.Fatalf("numeric both values and difference: %v", a)
	}
	if _, ok := diff["state"]; ok {
		t.Fatal("string fields have no difference")
	}
	// diff is always an object, empty when no numeric field was asked for.
	only := e.getJSON(t, "/v1/margin/compare?from=2026-11-10&to=2026-11-14&fields=state&size=1", 200)
	if d, ok := items(t, only)[0]["diff"].(map[string]any); !ok || len(d) != 0 {
		t.Fatalf("diff %v", items(t, only)[0]["diff"])
	}
	// A code on one side only: the other side is null, and so is its difference.
	d := byCode["000004"]
	if d["from"] != nil || d["to"].(map[string]any)["price"] != 5.5 || d["name"] != "D" || d["diff"].(map[string]any)["price"] != nil {
		t.Fatalf("appearing %v", d)
	}
	e5 := byCode["688001"]
	if e5["to"] != nil || e5["from"].(map[string]any)["price"] != 20.0 || e5["name"] != "E" {
		t.Fatalf("disappearing %v", e5)
	}
	// A null value on one side: both values are returned, the difference is null.
	c := byCode["300001"]
	if c["from"].(map[string]any)["price"] != nil || c["diff"].(map[string]any)["price"] != nil || c["to"].(map[string]any)["price"] != 7.0 {
		t.Fatalf("null value %v", c)
	}
}

func TestCompareChangedKeepsDifferingCodes(t *testing.T) {
	e := historyEnv(t)
	// state differs for 000001 (安全->临界), 300001 (潜伏->临界); 000004 (absent -> null state)
	// and 688001 (安全 -> absent) are on one side only, which counts as changed.
	out := e.getJSON(t, "/v1/margin/compare?from=2026-11-10&to=2026-11-14&changed=state", 200)
	if got := codesOf(items(t, out)); got != "000001,000004,300001,688001" {
		t.Fatalf("changed state: %s", got)
	}
	if fields := out["fields"]; fmt.Sprint(fields) != "[]" {
		t.Fatalf("fields %v", fields)
	}
	// Null differs from a value: 000004's state is 安全 on the 13th and null on the 14th.
	out = e.getJSON(t, "/v1/margin/compare?from=2026-11-13&to=2026-11-14&changed=state&fields=state", 200)
	list := items(t, out)
	if codesOf(list) != "000004" || list[0]["to"].(map[string]any)["state"] != nil || list[0]["from"].(map[string]any)["state"] != "安全" {
		t.Fatalf("null differs from a value: %v", list)
	}
	// Both null, or both equal, is not a change; name is a string field.
	if got := codesOf(items(t, e.getJSON(t, "/v1/margin/compare?from=2026-11-12&to=2026-11-13&changed=name", 200))); got != "" {
		t.Fatalf("name unchanged: %q", got)
	}
	for _, q := range []string{"changed=tags", "changed=price", "changed=frag", "changed=nope", "changed=", "changed=res_detail"} {
		if rec := e.get(t, "/v1/margin/compare?from=2026-11-10&to=2026-11-14&"+q, true); rec.Code != http.StatusBadRequest {
			t.Errorf("%s: %d", q, rec.Code)
		}
	}
}

func TestComparePagingBoundsAndRefusals(t *testing.T) {
	e := historyEnv(t)
	base := "/v1/margin/compare?from=2026-11-10&to=2026-11-14"
	out := e.getJSON(t, base+"&page=2&size=2", 200)
	if codesOf(items(t, out)) != "300001,600000" || out["total"] != 5.0 || out["page"] != 2.0 || out["size"] != 2.0 {
		t.Fatalf("page 2 %v", out)
	}
	if got := items(t, e.getJSON(t, base+"&page=9", 200)); len(got) != 0 {
		t.Fatalf("past the end %v", got)
	}
	e.getJSON(t, base+"&size=100", 200)
	e.getJSON(t, "/v1/margin/compare?from=2026-11-14&to=2026-11-10", 200) // reversed sides are allowed
	for _, q := range []string{"&size=101", "&size=0", "&page=0", "&page=x", "&fields=price,price", "&fields=nope",
		"&fields=price,chg,rz,ratio,dratio20,rz_chg5,rz_chg20,buf_call,buf_liq", "&x=1"} {
		if rec := e.get(t, base+q, true); rec.Code != http.StatusBadRequest {
			t.Errorf("%s: %d", q, rec.Code)
		}
	}
	for _, q := range []string{"", "?from=2026-11-10", "?to=2026-11-10", "?from=x&to=2026-11-10", "?from=2026-11-10&to=2026-11-10&to=2026-11-12"} {
		if rec := e.get(t, "/v1/margin/compare"+q, true); rec.Code != http.StatusBadRequest {
			t.Errorf("%q: %d", q, rec.Code)
		}
	}
	// A valid date that is not a history date (the gap day) has no data.
	for _, q := range []string{"?from=2026-11-11&to=2026-11-12", "?from=2026-11-12&to=2026-11-11"} {
		if rec := e.get(t, "/v1/margin/compare"+q, true); rec.Code != http.StatusNotFound {
			t.Errorf("%q: %d", q, rec.Code)
		}
	}
}

func TestStreak(t *testing.T) {
	e := historyEnv(t)
	q := func(extra string) map[string]any {
		return e.getJSON(t, "/v1/margin/streak?"+extra, 200)
	}
	// 000001, 300001 and 600000 are critical on the last three history dates (12th-14th).
	out := q("field=state&op=eq&value=临界&days=3")
	if codesOf(items(t, out)) != "000001,300001,600000" || out["total"] != 3.0 || out["complete"] != true {
		t.Fatalf("three days %v", out)
	}
	if list := items(t, out); list[0]["name"] != "B" {
		t.Fatalf("name %v", list[0])
	}
	if fmt.Sprint(out["dates"]) != "[2026-11-14 2026-11-13 2026-11-12]" {
		t.Fatalf("dates %v", out["dates"])
	}
	// Four days reach back over the gap: the dates used make it visible.
	out = q("field=state&op=eq&value=临界&days=4")
	if codesOf(items(t, out)) != "600000" || fmt.Sprint(out["dates"]) != "[2026-11-14 2026-11-13 2026-11-12 2026-11-10]" {
		t.Fatalf("four days %v", out)
	}
	// date picks the end; the default is the newest.
	out = q("field=state&op=eq&value=临界&days=2&date=2026-11-13")
	if fmt.Sprint(out["dates"]) != "[2026-11-13 2026-11-12]" || codesOf(items(t, out)) != "000001,300001,600000" {
		t.Fatalf("dated %v", out)
	}
	// null fails the condition: 300001's frag is null on the 13th, 000004's state is null on the 14th.
	if got := codesOf(items(t, q("field=frag&op=gte&value=50&days=3"))); got != "600000" {
		t.Fatalf("gte with a null: %s", got)
	}
	if got := codesOf(items(t, q("field=frag&op=lte&value=35&days=3"))); got != "000001,000004" {
		t.Fatalf("lte: %s", got)
	}
	if got := codesOf(items(t, q("field=state&op=eq&value=安全&days=2"))); got != "" {
		t.Fatalf("null state fails eq: %q", got)
	}
	if got := codesOf(items(t, q("field=price&op=eq&value=12&days=2"))); got != "600000" {
		t.Fatalf("numeric eq: %q", got)
	}
	// Fewer history dates than days: nobody can have met it on every one; the dates used show why.
	out = q("field=state&op=eq&value=临界&days=10")
	if out["total"] != 0.0 || out["complete"] != false || len(out["dates"].([]any)) != 4 {
		t.Fatalf("short history %v", out)
	}
	// Paging, ordered by code.
	out = q("field=state&op=eq&value=临界&days=3&page=2&size=2")
	if codesOf(items(t, out)) != "600000" || out["total"] != 3.0 {
		t.Fatalf("paged %v", out)
	}
	base := "/v1/margin/streak?field=state&op=eq&value=x&days=3"
	for _, extra := range []string{"&days=0", "&days=61", "&days=x", "&size=201", "&size=0", "&page=0", "&date=x", "&field=tags", "&field=nope",
		"&field=res_detail", "&op=gte", "&op=lt", "&unknown=1", "&field=name&op=gte"} {
		if rec := e.get(t, base+extra, true); rec.Code != http.StatusBadRequest && !strings.HasPrefix(extra, "&days=x") {
			t.Errorf("%s: %d", extra, rec.Code)
		} else if rec.Code != http.StatusBadRequest {
			t.Errorf("%s: %d", extra, rec.Code)
		}
	}
	for _, path := range []string{"field=frag&op=gte&days=3", "field=frag&op=gte&value=abc&days=3", "field=frag&op=gte&value=NaN&days=3",
		"field=frag&op=gte&value=Inf&days=3", "field=frag&op=gte&value=1", "field=frag&value=1&days=3", "op=gte&value=1&days=3",
		"field=state&op=eq&value=" + strings.Repeat("x", 65) + "&days=3"} {
		if rec := e.get(t, "/v1/margin/streak?"+path, true); rec.Code != http.StatusBadRequest {
			t.Errorf("%s: %d", path, rec.Code)
		}
	}
	e.getJSON(t, "/v1/margin/streak?field=state&op=eq&value=x&days=60&size=200", 200)
	// A valid date that is not a history date.
	if rec := e.get(t, base+"&date=2026-11-11", true); rec.Code != http.StatusNotFound {
		t.Errorf("gap date: %d", rec.Code)
	}
	if rec := newBareEnvGet(t, "/v1/margin/streak?field=state&op=eq&value=x&days=1"); rec.Code != http.StatusNotFound {
		t.Errorf("no history at all: %d", rec.Code)
	}
}

func newBareEnvGet(t *testing.T, path string) *httptest.ResponseRecorder {
	return newBareEnv(t).get(t, path, true)
}

func TestCounts(t *testing.T) {
	e := historyEnv(t)
	out := e.getJSON(t, "/v1/margin/counts?field=state", 200)
	list := items(t, out)
	if len(list) != 4 || list[0]["date"] != "2026-11-10" || list[3]["date"] != "2026-11-14" {
		t.Fatalf("dates oldest first: %v", list)
	}
	counts := func(i int) map[string]any { return list[i]["counts"].(map[string]any) }
	if c := counts(0); len(c) != 3 || c["安全"] != 2.0 || c["潜伏"] != 1.0 || c["临界"] != 1.0 {
		t.Fatalf("10th %v", c)
	}
	if c := counts(3); len(c) != 1 || c["临界"] != 3.0 || list[3]["nulls"] != 1.0 { // nulls are counted apart
		t.Fatalf("14th %v nulls %v", c, list[3]["nulls"])
	}
	if list[0]["nulls"] != 0.0 {
		t.Fatalf("nulls %v", list[0]["nulls"])
	}
	out = e.getJSON(t, "/v1/margin/counts?field=level&from=2026-11-12&to=2026-11-13", 200)
	if got := items(t, out); len(got) != 2 || fmt.Sprint(got[0]["counts"]) != "map[高:4]" {
		t.Fatalf("window %v", got)
	}
	for _, q := range []string{"", "?field=price", "?field=code", "?field=name", "?field=tags", "?field=sw1", "?field=res_detail",
		"?field=state&from=x", "?field=state&to=2026-13-01", "?field=state&from=2026-11-14&to=2026-11-10", "?field=state&x=1",
		"?field=state&field=level"} {
		if rec := e.get(t, "/v1/margin/counts"+q, true); rec.Code != http.StatusBadRequest {
			t.Errorf("%q: %d", q, rec.Code)
		}
	}
	// Each module's allowlist.
	for module, fields := range countFields {
		for _, f := range fields {
			e.getJSON(t, "/v1/"+module+"/counts?field="+f, 200)
		}
	}
	for _, q := range []string{"/v1/panorama/counts?field=state", "/v1/etf/counts?field=state", "/v1/margin/counts?field=cat"} {
		if rec := e.get(t, q, true); rec.Code != http.StatusBadRequest {
			t.Errorf("%s: %d", q, rec.Code)
		}
	}
}

func TestCountsCapsAtFiveHundredDatesAndStaysWithinOneMiB(t *testing.T) {
	e := newBareEnv(t)
	// 31 industries each day, 520 days.
	rows := make([]map[string]any, 31)
	for i := range rows {
		rows[i] = map[string]any{"code": strconv.Itoa(100000 + i), "name": "n", "sw1": "行业" + strconv.Itoa(i)}
	}
	start := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
	for i := 0; i < 520; i++ {
		putHistory(t, e.srv.store, "panorama", start.AddDate(0, 0, i).Format("2006-01-02"), rows)
	}
	rec := e.get(t, "/v1/panorama/counts?field=sw1", true)
	if rec.Code != 200 || rec.Body.Len() >= maxResponse {
		t.Fatalf("%d, %d bytes", rec.Code, rec.Body.Len())
	}
	out := decode(t, rec)
	if len(items(t, out)) != 500 || out["truncated"] != true || out["next_to"] != start.AddDate(0, 0, 19).Format("2006-01-02") {
		t.Fatalf("%d items, %v %v", len(items(t, out)), out["truncated"], out["next_to"])
	}
	// More than 60 files: the scan bypasses the cache.
	if n := len(e.srv.store.hist.cache); n != 0 {
		t.Fatalf("a 500-file scan filled the cache with %d entries", n)
	}
}

func TestResponsesAtTheirCapsStayWithinOneMiB(t *testing.T) {
	e := newBareEnv(t)
	long := strings.Repeat("占比畸高|", 20)
	rows := make([]map[string]any, 220)
	for i := range rows {
		rows[i] = map[string]any{"code": fmt.Sprintf("%06d", i), "name": "一个比较长的股票名称", "price": 123456.789, "chg": -1.5, "rz": 1e9,
			"ratio": 1.5, "dratio20": 0.12345, "rz_chg5": 1.1, "rz_chg20": 2.2, "buf_call": 3.3, "buf_liq": 4.4, "pnl": 5.5,
			"score": 6.6, "frag": 7.7, "state": "临界", "level": "高", "tags": long}
	}
	start := time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC)
	for i := 0; i < 260; i++ {
		putHistory(t, e.srv.store, "margin", start.AddDate(0, 0, i).Format("2006-01-02"), rows)
	}
	eight := "price,chg,rz,ratio,dratio20,rz_chg5,rz_chg20,buf_call"
	last := start.AddDate(0, 0, 259).Format("2006-01-02")
	for name, path := range map[string]string{
		"history": "/v1/margin/history?code=000001&fields=" + eight,
		"compare": "/v1/margin/compare?from=" + start.Format("2006-01-02") + "&to=" + last + "&size=100&fields=" + eight,
		"streak":  "/v1/margin/streak?field=state&op=eq&value=临界&days=60&size=200",
		"counts":  "/v1/margin/counts?field=state",
	} {
		rec := e.get(t, path, true)
		if rec.Code != 200 || rec.Body.Len() >= maxResponse {
			t.Errorf("%s: %d, %d bytes", name, rec.Code, rec.Body.Len())
		}
	}
	// A response that cannot fit is refused by the existing 422 rule, never truncated.
	huge := []map[string]any{{"code": "1", "name": "x", "tags": strings.Repeat("a", 600<<10)}, {"code": "2", "name": "y", "tags": strings.Repeat("b", 600<<10)}}
	putHistory(t, e.srv.store, "margin", "2027-01-01", huge)
	putHistory(t, e.srv.store, "margin", "2027-01-02", huge)
	rec := e.get(t, "/v1/margin/compare?from=2027-01-01&to=2027-01-02&fields=tags", true)
	if rec.Code != http.StatusUnprocessableEntity {
		t.Fatalf("oversized: %d %d bytes", rec.Code, rec.Body.Len())
	}
}

func TestHistoryQueriesNeverReadSnapshots(t *testing.T) {
	e := newBareEnv(t)
	installTest(t, e.srv.store, "margin", "2026-11-18")
	if err := os.RemoveAll(e.srv.store.root); err != nil {
		t.Fatal(err)
	}
	e.getJSON(t, "/v1/margin/history/dates", 200)
	e.getJSON(t, "/v1/margin/counts?field=state", 200)
	out := e.getJSON(t, "/v1/margin/history?code=600000&fields=frag", 200)
	if list := items(t, out); len(list) != 1 || list[0]["frag"] != 90.0 {
		t.Fatalf("%v", list)
	}
}

func TestOneHistoryQueryAtATimeAndTheRestGetBusy(t *testing.T) {
	e := historyEnv(t)
	hist := e.srv.store.hist
	entered, release := make(chan struct{}), make(chan struct{})
	var once sync.Once
	hist.beforeFile = func(string) {
		once.Do(func() { close(entered); <-release })
	}
	first := make(chan *httptest.ResponseRecorder, 1)
	go func() { first <- e.get(t, "/v1/margin/counts?field=state", true) }()
	<-entered
	for _, path := range []string{"/v1/margin/counts?field=state", "/v1/margin/history?code=1&fields=price",
		"/v1/margin/compare?from=2026-11-10&to=2026-11-12", "/v1/margin/streak?field=state&op=eq&value=x&days=1"} {
		rec := e.get(t, path, true)
		if rec.Code != http.StatusTooManyRequests || decode(t, rec)["error"] != "busy" {
			t.Errorf("%s while busy: %d %s", path, rec.Code, rec.Body.String())
		}
	}
	// Listing dates and the snapshot routes are not history queries.
	e.getJSON(t, "/v1/margin/history/dates", 200)
	close(release)
	if rec := <-first; rec.Code != 200 {
		t.Fatalf("first query: %d", rec.Code)
	}
	e.getJSON(t, "/v1/margin/counts?field=state", 200) // the gate is free again
}

func TestHistoryQueryPastTheDeadlineIs409QueryTimeout(t *testing.T) {
	e := historyEnv(t)
	hist := e.srv.store.hist
	hist.timeout = 60 * time.Millisecond
	hist.beforeFile = func(string) { time.Sleep(40 * time.Millisecond) }
	rec := e.get(t, "/v1/margin/counts?field=state", true)
	if rec.Code != http.StatusConflict || decode(t, rec)["error"] != "query_timeout" {
		t.Fatalf("%d %s", rec.Code, rec.Body.String())
	}
	// The gate was released.
	hist.beforeFile, hist.timeout = nil, queryTimeout
	e.getJSON(t, "/v1/margin/counts?field=state", 200)
	// The deadline is checked before each file, so even the first can time out.
	hist.timeout = -time.Second
	if rec := e.get(t, "/v1/margin/history?code=600000&fields=price", true); rec.Code != http.StatusConflict {
		t.Fatalf("%d", rec.Code)
	}
	if rec := e.get(t, "/v1/margin/compare?from=2026-11-10&to=2026-11-12", true); rec.Code != http.StatusConflict {
		t.Fatalf("%d", rec.Code)
	}
}

func TestACorruptHistoryFileIsUnavailableNotSkipped(t *testing.T) {
	e := historyEnv(t)
	s := e.srv.store
	dir := filepath.Join(s.histRoot, "margin")
	// A file whose metadata names another date (a copy placed by hand).
	raw, _ := os.ReadFile(filepath.Join(dir, "2026-11-12.parquet"))
	putHistoryFile(t, filepath.Join(dir, "2026-11-15.parquet"), raw)
	rec := e.get(t, "/v1/margin/counts?field=state", true)
	if rec.Code != http.StatusConflict || decode(t, rec)["error"] != "unavailable" {
		t.Fatalf("%d %s", rec.Code, rec.Body.String())
	}
	putHistoryFile(t, filepath.Join(dir, "2026-11-15.parquet"), []byte("garbage"))
	if rec := e.get(t, "/v1/margin/counts?field=state", true); rec.Code != http.StatusConflict {
		t.Fatalf("garbage: %d", rec.Code)
	}
	for _, name := range []string{"2026-11-15.parquet", "2026-11-15.parquet.sha256"} {
		if err := os.Remove(filepath.Join(dir, name)); err != nil {
			t.Fatal(err)
		}
	}
	e.getJSON(t, "/v1/margin/counts?field=state", 200)
}

// ---- cache ----

func priceOn(t *testing.T, e testEnv, date string) any {
	t.Helper()
	out := e.getJSON(t, "/v1/margin/history?code=600000&fields=price&from="+date+"&to="+date, 200)
	list := items(t, out)
	if len(list) != 1 {
		t.Fatalf("%s: %v", date, list)
	}
	return list[0]["price"]
}

func TestHistoryCacheIsFilledAndServesHits(t *testing.T) {
	e := historyEnv(t)
	s := e.srv.store
	if priceOn(t, e, "2026-11-12") != 11.0 {
		t.Fatal("value")
	}
	entry := s.hist.cache["margin/2026-11-12"]
	if entry == nil || entry.cols["price"] == nil || entry.cols["code"] == nil || entry.cols["frag"] != nil {
		t.Fatalf("only the needed columns are cached: %+v", entry)
	}
	// Another column is added to the same entry.
	e.getJSON(t, "/v1/margin/history?code=600000&fields=frag&from=2026-11-12&to=2026-11-12", 200)
	if entry = s.hist.cache["margin/2026-11-12"]; entry.cols["frag"] == nil || entry.cols["price"] == nil {
		t.Fatalf("columns not merged: %+v", entry.cols)
	}
	if s.hist.bytes <= 0 {
		t.Fatal("bytes not accounted")
	}
	// A query of up to 60 files uses the cache.
	e.getJSON(t, "/v1/margin/counts?field=state", 200)
	if len(s.hist.cache) != 4 {
		t.Fatalf("%d entries", len(s.hist.cache))
	}
}

func TestHistoryCacheNeverServesAReplacedOrRemovedFile(t *testing.T) {
	e := historyEnv(t)
	s := e.srv.store
	priceOn(t, e, "2026-11-12")
	path := filepath.Join(s.histRoot, "margin", "2026-11-12.parquet")
	// Replaced by hand (a restore, a doc 185 import), with no install and no
	// call into the store: the next use must notice.
	newRows := []map[string]any{mrow("600000", "A", 99.0, 1.0, "临界")}
	putHistoryFile(t, path, historyFile(t, histSpec{module: "margin", asOf: "2026-11-12", rows: newRows}))
	if got := priceOn(t, e, "2026-11-12"); got != 99.0 {
		t.Fatalf("stale columns served: %v", got)
	}
	// Rewritten in place with the same size is still a new file identity (mtime).
	same := historyFile(t, histSpec{module: "margin", asOf: "2026-11-12", rows: []map[string]any{mrow("600000", "A", 98.0, 1.0, "临界")}})
	time.Sleep(10 * time.Millisecond)
	putHistoryFile(t, path, same)
	if got := priceOn(t, e, "2026-11-12"); got != 98.0 {
		t.Fatalf("rewritten file served stale: %v", got)
	}
	// Removed by hand: gone at once, from the dates list and the queries.
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if rec := e.get(t, "/v1/margin/compare?from=2026-11-10&to=2026-11-12", true); rec.Code != http.StatusNotFound {
		t.Fatalf("removed date still served: %d", rec.Code)
	}
	if got := fmt.Sprint(e.getJSON(t, "/v1/margin/history/dates", 200)["dates"]); strings.Contains(got, "2026-11-12") {
		t.Fatal(got)
	}
	if _, cached := s.hist.cache["margin/2026-11-12"]; cached {
		t.Fatal("entry of a removed file kept")
	}
}

func TestInstallReplacesCachedHistory(t *testing.T) {
	s := NewStore(t.TempDir())
	installTest(t, s, "margin", "2026-11-18", mrow("600000", "A", 1.0, 1.0, "临界"))
	read := func() any {
		q, done, err := s.beginHistory()
		if err != nil {
			t.Fatal(err)
		}
		defer done()
		view, err := q.load("margin", "2026-11-18", "price")
		if err != nil {
			t.Fatal(err)
		}
		return view.value("price", 0)
	}
	if read() != 1.0 {
		t.Fatal("first")
	}
	installTest(t, s, "margin", "2026-11-18", mrow("600000", "A", 2.0, 1.0, "临界"))
	if got := read(); got != 2.0 {
		t.Fatalf("stale after install: %v", got)
	}
}

func TestAnInstallRacingHistoryQueriesLeavesNoStaleColumns(t *testing.T) {
	s := NewStore(t.TempDir())
	installTest(t, s, "margin", "2026-11-18", mrow("600000", "A", 0.0, 1.0, "临界"))
	stop := make(chan struct{})
	var wg sync.WaitGroup
	for g := 0; g < 3; g++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for {
				select {
				case <-stop:
					return
				default:
				}
				q, done, err := s.beginHistory()
				if err != nil {
					continue // busy
				}
				_, _ = q.load("margin", "2026-11-18", "price", "state")
				done()
			}
		}()
	}
	for i := 1; i <= 15; i++ {
		installTest(t, s, "margin", "2026-11-18", mrow("600000", "A", float64(i), 1.0, "临界"))
		var got any
		for {
			q, done, err := s.beginHistory()
			if err != nil {
				time.Sleep(time.Millisecond)
				continue
			}
			view, err := q.load("margin", "2026-11-18", "price")
			if err != nil {
				t.Fatal(err)
			}
			got = view.value("price", 0)
			done()
			break
		}
		if got != float64(i) {
			close(stop)
			wg.Wait()
			t.Fatalf("after install %d the query read %v", i, got)
		}
	}
	close(stop)
	wg.Wait()
}

func TestHistoryCacheStaysWithinItsBudgetAndEvictsLeastRecentlyUsed(t *testing.T) {
	e := historyEnv(t)
	s := e.srv.store
	priceOn(t, e, "2026-11-10")
	oneEntry := s.hist.bytes
	s.hist.budget = oneEntry*2 + oneEntry/2 // room for two entries
	for _, d := range []string{"2026-11-12", "2026-11-13", "2026-11-14"} {
		priceOn(t, e, d)
		if s.hist.bytes > s.hist.budget {
			t.Fatalf("cache %d over budget %d", s.hist.bytes, s.hist.budget)
		}
	}
	if len(s.hist.cache) == 0 || len(s.hist.cache) > 2 {
		t.Fatalf("%d entries", len(s.hist.cache))
	}
	if _, ok := s.hist.cache["margin/2026-11-14"]; !ok {
		t.Fatal("newest entry evicted")
	}
	if _, ok := s.hist.cache["margin/2026-11-10"]; ok {
		t.Fatal("least recently used entry kept")
	}
	// An entry larger than the whole budget is not cached.
	for _, d := range []string{"2026-11-10", "2026-11-12", "2026-11-13", "2026-11-14"} {
		s.hist.drop("margin/" + d)
	}
	s.hist.budget = 10
	priceOn(t, e, "2026-11-10")
	if len(s.hist.cache) != 0 || s.hist.bytes != 0 {
		t.Fatalf("%d entries, %d bytes", len(s.hist.cache), s.hist.bytes)
	}
}

func TestScansOverSixtyFilesBypassTheCache(t *testing.T) {
	e := newBareEnv(t)
	s := e.srv.store
	start := time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC)
	for i := 0; i < 61; i++ {
		putHistory(t, s, "etf", start.AddDate(0, 0, i).Format("2006-01-02"), []map[string]any{{"code": "588000", "name": "X", "cat": "c", "cum20": 1.0}})
	}
	e.getJSON(t, "/v1/etf/counts?field=cat", 200)
	if len(s.hist.cache) != 0 {
		t.Fatalf("61 files filled the cache: %d", len(s.hist.cache))
	}
	// Sixty files are still cached.
	e.getJSON(t, "/v1/etf/counts?field=cat&from=2025-01-02", 200)
	if len(s.hist.cache) != 60 {
		t.Fatalf("60 files cached %d", len(s.hist.cache))
	}
	// And a long scan does not evict them.
	e.getJSON(t, "/v1/etf/counts?field=cat", 200)
	if len(s.hist.cache) != 60 {
		t.Fatalf("a long scan changed the cache: %d", len(s.hist.cache))
	}
}

func TestFieldNamesOutsideTheSchemaAreRefusedEverywhere(t *testing.T) {
	e := historyEnv(t)
	for _, f := range []string{"res_detail", "py", "pld_n", "sw1", "cat", "s_value", "id", "date", "CODE", "price%20", "a.b", "%00", "", strings.Repeat("a", 100)} {
		escaped := url.QueryEscape(f)
		for _, path := range []string{
			"/v1/margin/history?code=600000&fields=" + escaped,
			"/v1/margin/compare?from=2026-11-10&to=2026-11-12&fields=" + escaped,
			"/v1/margin/compare?from=2026-11-10&to=2026-11-12&changed=" + escaped,
			"/v1/margin/streak?days=1&op=eq&value=1&field=" + escaped,
			"/v1/margin/counts?field=" + escaped,
		} {
			if rec := e.get(t, path, true); rec.Code != http.StatusBadRequest {
				t.Errorf("%s: %d", path, rec.Code)
			}
		}
	}
}

func TestEveryModulesSchemaIsQueryable(t *testing.T) {
	e := newBareEnv(t)
	for _, module := range []string{"margin", "panorama", "etf"} {
		var names []string
		row := map[string]any{"code": "1", "name": "n"}
		for _, c := range historySchemas[module] {
			names = append(names, c.name)
			if c.str && c.name != "code" && c.name != "name" {
				row[c.name] = "v"
			} else if !c.str {
				row[c.name] = 1.5
			}
		}
		putHistory(t, e.srv.store, module, "2026-11-10", []map[string]any{row})
		putHistory(t, e.srv.store, module, "2026-11-11", []map[string]any{row})
		for _, name := range names {
			path := "/v1/" + module + "/history?code=1&fields=" + name
			if out := items(t, e.getJSON(t, path, 200)); len(out) != 2 {
				t.Errorf("%s: %v", path, out)
			}
		}
	}
}
