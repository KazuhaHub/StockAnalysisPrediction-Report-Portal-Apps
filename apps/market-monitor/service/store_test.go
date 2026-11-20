package main

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

func testSnapshot(module, asOf string, rows ...map[string]any) []byte {
	if rows == nil {
		rows = []map[string]any{
			{"code": "600000", "name": "A", "frag": 90.0, "state": "临界", "tags": "价跌加杠杆|占比畸高"},
			{"code": "000001", "name": "B", "frag": 30.0, "state": "安全", "tags": ""},
			{"code": "300001", "name": "C", "frag": nil, "state": "潜伏", "tags": "占比畸高"},
		}
	}
	raw, _ := json.Marshal(map[string]any{
		"format":  snapshotFormat,
		"module":  module,
		"as_of":   asOf,
		"summary": map[string]any{"n": len(rows)},
		"rows":    rows,
		"details": map[string]any{"600000": map[string]any{"hist": []float64{1, 2, 3}}},
	})
	return raw
}

func TestStoreInstallsAndLoadsLatest(t *testing.T) {
	s := NewStore(t.TempDir())
	for _, d := range []string{"2026-11-17", "2026-11-18", "2026-11-16"} {
		if _, err := s.Install("margin", testSnapshot("margin", d)); err != nil {
			t.Fatal(d, err)
		}
	}
	dates, err := s.Dates("margin")
	if err != nil || strings.Join(dates, ",") != "2026-11-18,2026-11-17,2026-11-16" {
		t.Fatalf("dates %v %v", dates, err)
	}
	snap, err := s.Load("margin", "")
	if err != nil || snap.AsOf != "2026-11-18" {
		t.Fatalf("latest %v %v", snap, err)
	}
	snap, err = s.Load("margin", "2026-11-16")
	if err != nil || snap.AsOf != "2026-11-16" || len(snap.Rows) != 3 {
		t.Fatalf("by date %v %v", snap, err)
	}
}

func TestStoreReinstallReplacesTheSameDate(t *testing.T) {
	s := NewStore(t.TempDir())
	if _, err := s.Install("margin", testSnapshot("margin", "2026-11-18")); err != nil {
		t.Fatal(err)
	}
	one := []map[string]any{{"code": "600000", "name": "A"}}
	if _, err := s.Install("margin", testSnapshot("margin", "2026-11-18", one...)); err != nil {
		t.Fatal(err)
	}
	snap, err := s.Load("margin", "2026-11-18")
	if err != nil || len(snap.Rows) != 1 {
		t.Fatalf("cache not refreshed: %v %v", snap, err)
	}
}

func TestStoreRefusesInvalidSnapshots(t *testing.T) {
	s := NewStore(t.TempDir())
	cases := map[string][]byte{
		"unknown module":   testSnapshot("../x", "2026-11-18"),
		"module mismatch":  []byte(strings.Replace(string(testSnapshot("margin", "2026-11-18")), `"module":"margin"`, `"module":"etf"`, 1)),
		"bad date":         testSnapshot("margin", "2026-13-40"),
		"path date":        testSnapshot("margin", "../../etc"),
		"not json":         []byte("{"),
		"wrong format":     []byte(strings.Replace(string(testSnapshot("margin", "2026-11-18")), snapshotFormat, "other/1", 1)),
		"duplicate code":   testSnapshot("margin", "2026-11-18", map[string]any{"code": "1"}, map[string]any{"code": "1"}),
		"missing code":     testSnapshot("margin", "2026-11-18", map[string]any{"name": "x"}),
		"trailing content": append(testSnapshot("margin", "2026-11-18"), []byte(" {}")...),
	}
	for name, raw := range cases {
		module := "margin"
		if name == "unknown module" {
			module = "../x"
		}
		if _, err := s.Install(module, raw); err == nil {
			t.Errorf("%s: accepted", name)
		}
	}
	if dates, _ := s.Dates("margin"); len(dates) != 0 {
		t.Fatalf("refused snapshot left files: %v", dates)
	}
}

func TestStoreLoadRefusesUnknownInput(t *testing.T) {
	s := NewStore(t.TempDir())
	if _, err := s.Load("margin", ""); !errors.Is(err, errNotFound) {
		t.Fatalf("empty store: %v", err)
	}
	if _, err := s.Load("nope", ""); !errors.Is(err, errNotFound) {
		t.Fatalf("unknown module: %v", err)
	}
	if _, err := s.Load("margin", "../../x"); err == nil {
		t.Fatal("path date accepted")
	}
}

func TestStoreIgnoresStrayFiles(t *testing.T) {
	root := t.TempDir()
	s := NewStore(root)
	if _, err := s.Install("etf", testSnapshot("etf", "2026-11-16")); err != nil {
		t.Fatal(err)
	}
	dir := filepath.Join(root, "snapshots", "etf")
	for _, name := range []string{"notes.txt", "2026-11-19.json.tmp", "latest.json"} {
		if err := os.WriteFile(filepath.Join(dir, name), []byte("x"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	dates, err := s.Dates("etf")
	if err != nil || len(dates) != 1 || dates[0] != "2026-11-16" {
		t.Fatalf("dates %v %v", dates, err)
	}
}

func TestQueryRowsFiltersSortsAndPages(t *testing.T) {
	rows := []map[string]any{
		{"code": "600000", "name": "浦发银行", "frag": 90.0, "state": "临界", "tags": "价跌加杠杆|占比畸高"},
		{"code": "000001", "name": "平安银行", "frag": 30.0, "state": "安全", "tags": ""},
		{"code": "300001", "name": "特锐德", "frag": nil, "state": "潜伏", "tags": "占比畸高"},
		{"code": "600036", "name": "招商银行", "frag": 50.0, "state": "安全", "tags": ""},
	}
	page, total := queryRows(rows, rowQuery{Page: 1, Size: 2, Sort: "frag", Desc: true})
	if total != 4 || len(page) != 2 || page[0]["code"] != "600000" || page[1]["code"] != "600036" {
		t.Fatalf("sorted page %v %d", page, total)
	}
	page, _ = queryRows(rows, rowQuery{Page: 2, Size: 2, Sort: "frag", Desc: true})
	if len(page) != 2 || page[1]["code"] != "300001" {
		t.Fatalf("nulls must sort last: %v", page)
	}
	page, total = queryRows(rows, rowQuery{Page: 1, Size: 10, Filters: map[string]string{"state": "安全"}})
	if total != 2 {
		t.Fatalf("equality filter %v", page)
	}
	page, total = queryRows(rows, rowQuery{Page: 1, Size: 10, Filters: map[string]string{"tags": "占比畸高"}})
	if total != 2 {
		t.Fatalf("tag token filter %v", page)
	}
	page, total = queryRows(rows, rowQuery{Page: 1, Size: 10, Search: "银行"})
	if total != 3 {
		t.Fatalf("name search %v", page)
	}
	page, total = queryRows(rows, rowQuery{Page: 1, Size: 10, Search: "6000"})
	if total != 2 {
		t.Fatalf("code prefix search %v", page)
	}
	page, total = queryRows(rows, rowQuery{Page: 9, Size: 10})
	if total != 4 || len(page) != 0 {
		t.Fatalf("page past the end %v", page)
	}
}

func TestStoreNeverServesAStaleSnapshotAfterInstall(t *testing.T) {
	s := NewStore(t.TempDir())
	if _, err := s.Install("margin", testSnapshot("margin", "2026-11-18")); err != nil {
		t.Fatal(err)
	}
	stop := make(chan struct{})
	done := make(chan struct{})
	go func() {
		defer close(done)
		for {
			select {
			case <-stop:
				return
			default:
				_, _ = s.Load("margin", "2026-11-18")
			}
		}
	}()
	for i := 1; i <= 30; i++ {
		rows := make([]map[string]any, i)
		rows[0] = map[string]any{"code": "600000"} // carries the fixture's detail
		for j := 1; j < i; j++ {
			rows[j] = map[string]any{"code": strconv.Itoa(j)}
		}
		if _, err := s.Install("margin", testSnapshot("margin", "2026-11-18", rows...)); err != nil {
			t.Fatal(err)
		}
		snap, err := s.Load("margin", "2026-11-18")
		if err != nil || len(snap.Rows) != i {
			close(stop)
			<-done
			t.Fatalf("after install %d: got %d rows (%v)", i, len(snap.Rows), err)
		}
	}
	close(stop)
	<-done
}

func TestStoreCacheStaysWithinItsByteBudget(t *testing.T) {
	s := NewStore(t.TempDir())
	s.cacheBudget = 3000
	for _, d := range []string{"2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-14"} {
		if _, err := s.Install("margin", testSnapshot("margin", d)); err != nil {
			t.Fatal(err)
		}
		if _, err := s.Load("margin", d); err != nil {
			t.Fatal(err)
		}
		if s.cachedBytes > s.cacheBudget {
			t.Fatalf("cache %d bytes over budget %d", s.cachedBytes, s.cacheBudget)
		}
	}
	if len(s.cache) == 0 {
		t.Fatal("nothing cached")
	}
}

func TestStoreStopsServingADateDeletedByHand(t *testing.T) {
	root := t.TempDir()
	s := NewStore(root)
	if _, err := s.Install("margin", testSnapshot("margin", "2026-11-18")); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Load("margin", "2026-11-18"); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(filepath.Join(root, "snapshots", "margin", "2026-11-18.json")); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Load("margin", "2026-11-18"); !errors.Is(err, errNotFound) {
		t.Fatalf("deleted date still served: %v", err)
	}
}

// TestSnapshotsFromARealRun validates job outputs produced outside the test,
// e.g. by running pipeline/mm_job.py against real data. It runs only when
// MM_SNAPSHOT_DIR names a directory of <module>.json files.
func TestSnapshotsFromARealRun(t *testing.T) {
	dir := os.Getenv("MM_SNAPSHOT_DIR")
	if dir == "" {
		t.Skip("MM_SNAPSHOT_DIR not set")
	}
	entries, err := os.ReadDir(dir)
	if err != nil || len(entries) == 0 {
		t.Fatalf("no snapshots in %s: %v", dir, err)
	}
	s := NewStore(t.TempDir())
	for _, e := range entries {
		raw, err := os.ReadFile(filepath.Join(dir, e.Name()))
		if err != nil {
			t.Fatal(err)
		}
		module := strings.TrimSuffix(e.Name(), ".json")
		asOf, err := s.Install(module, raw)
		if err != nil {
			t.Fatalf("%s: %v", e.Name(), err)
		}
		snap, err := s.Load(module, asOf)
		if err != nil {
			t.Fatal(err)
		}
		page, total := queryRows(snap.Rows, rowQuery{Page: 1, Size: maxPageSize})
		body, _ := json.Marshal(map[string]any{"items": page})
		summary, _ := json.Marshal(snap.Summary)
		t.Logf("%s as_of=%s rows=%d first-page=%dB summary=%dB", module, asOf, total, len(body), len(summary))
		if len(body) > maxResponse || len(summary) > maxResponse {
			t.Errorf("%s: a response would exceed the relay limit", module)
		}
		largest := 0
		for i, row := range snap.Rows {
			code := row["code"].(string)
			detail, _ := json.Marshal(map[string]any{"row": snap.Rows[i], "detail": snap.Details[code]})
			largest = max(largest, len(detail))
		}
		if largest > maxResponse {
			t.Errorf("%s: a row detail response would exceed the relay limit (%d B)", module, largest)
		}
	}
}
