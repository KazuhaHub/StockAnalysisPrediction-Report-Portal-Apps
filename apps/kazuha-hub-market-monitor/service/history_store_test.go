package main

import (
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/parquet-go/parquet-go/compress"
	pgzip "github.com/parquet-go/parquet-go/compress/gzip"
	"github.com/parquet-go/parquet-go/compress/lz4"
	"github.com/parquet-go/parquet-go/compress/snappy"
	"github.com/parquet-go/parquet-go/compress/uncompressed"
	"github.com/parquet-go/parquet-go/compress/zstd"
)

func exists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

func files(t *testing.T, dir string) []string {
	t.Helper()
	entries, err := os.ReadDir(dir)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		t.Fatal(err)
	}
	var out []string
	for _, e := range entries {
		out = append(out, e.Name())
	}
	return out
}

// TestPyarrowHistoryFilesAreAccepted installs history files written by
// mm_job.py (pyarrow, zstd, ARROW:schema metadata). The files in
// testdata/pyarrow come from testdata/make_history.py (as_of 2026-11-16);
// regenerate them with it if the format changes.
func TestPyarrowHistoryFilesAreAccepted(t *testing.T) {
	checkPyarrowFiles(t, filepath.Join("testdata", "pyarrow"))
}

// TestHistoryFilesFromTheImage does the same with files that CI wrote inside
// the backend image as the restricted container user (MM_IMAGE_HISTORY_DIR).
func TestHistoryFilesFromTheImage(t *testing.T) {
	dir := os.Getenv("MM_IMAGE_HISTORY_DIR")
	if dir == "" {
		t.Skip("MM_IMAGE_HISTORY_DIR not set")
	}
	checkPyarrowFiles(t, dir)
}

func checkPyarrowFiles(t *testing.T, dir string) {
	fixtures := map[string][]map[string]any{
		"margin":   {{"code": "600000"}, {"code": "000001"}, {"code": "300001"}},
		"panorama": {{"code": "000001"}, {"code": "600000"}},
		"etf":      {{"code": "588000"}, {"code": "510300"}},
	}
	s := NewStore(t.TempDir())
	for module, rows := range fixtures {
		history, err := os.ReadFile(filepath.Join(dir, module+".history.parquet"))
		if err != nil {
			t.Fatal(err)
		}
		if _, err := s.Install(module, testSnapshot(module, "2026-11-16", rows...), history); err != nil {
			t.Fatalf("%s: %v", module, err)
		}
	}
	q, done, _ := s.beginHistory()
	defer done()
	view, err := q.load("margin", "2026-11-16", "price", "frag", "state", "tags")
	if err != nil {
		t.Fatal(err)
	}
	i, _ := view.rowOf("000001")
	if v := view.value("price", i); v != nil {
		t.Fatalf("null price read as %v", v)
	}
	if v := view.value("state", i); v != "安全" {
		t.Fatalf("state %v", v)
	}
	if v := view.value("tags", i); v != "" {
		t.Fatalf("empty string must stay a string, got %v", v)
	}
	i, _ = view.rowOf("600000")
	if v := view.value("price", i); v != 10.5 {
		t.Fatalf("price %v", v)
	}
	pano, err := q.load("panorama", "2026-11-16", "name", "sw1", "pe", "s_value")
	if err != nil {
		t.Fatal(err)
	}
	if v := pano.value("name", 0); v != "平安银行" {
		t.Fatalf("name %v", v)
	}
}

func TestInstallRefusesInvalidHistory(t *testing.T) {
	rows := defaultRows()
	good := histSpec{module: "margin", asOf: "2026-11-18", rows: rows}
	with := func(f func(*histSpec)) histSpec {
		s := good
		f(&s)
		return s
	}
	badCols := func(f func([]histCol) []histCol) histSpec {
		return with(func(s *histSpec) { s.columns = f(append([]histCol(nil), historySchemas["margin"]...)) })
	}
	manyRows := make([]map[string]any, 20001)
	for i := range manyRows {
		manyRows[i] = map[string]any{"code": strconv.Itoa(i)}
	}
	cases := map[string]histSpec{
		"wrong format":   with(func(s *histSpec) { s.format = "market-monitor.history/2" }),
		"wrong module":   with(func(s *histSpec) { s.metaModule = "etf" }),
		"wrong as_of":    with(func(s *histSpec) { s.metaAsOf = "2026-11-17" }),
		"no format":      with(func(s *histSpec) { s.dropMeta = "format" }),
		"no module":      with(func(s *histSpec) { s.dropMeta = "module" }),
		"no as_of":       with(func(s *histSpec) { s.dropMeta = "as_of" }),
		"required":       with(func(s *histSpec) { s.required = true }),
		"missing column": badCols(func(c []histCol) []histCol { return c[:len(c)-1] }),
		"extra column":   badCols(func(c []histCol) []histCol { return append(c, histCol{"extra", false}) }),
		"renamed column": badCols(func(c []histCol) []histCol { c[2].name = "Price"; return c }),
		"retyped column": badCols(func(c []histCol) []histCol { c[2].str = true; return c }),
		"retyped string": badCols(func(c []histCol) []histCol { c[1].str = false; return c }),
		"reordered":      badCols(func(c []histCol) []histCol { c[0], c[1] = c[1], c[0]; return c }),
		"another schema": with(func(s *histSpec) { s.columns = historySchemas["etf"] }),
		"empty code":     with(func(s *histSpec) { s.rows = []map[string]any{{"code": ""}, rows[1], rows[2]} }),
		"null code":      with(func(s *histSpec) { s.rows = []map[string]any{{"name": "x"}, rows[1], rows[2]} }),
		"long code":      with(func(s *histSpec) { s.rows = []map[string]any{{"code": strings.Repeat("9", 17)}, rows[1], rows[2]} }),
		"duplicate code": with(func(s *histSpec) { s.rows = []map[string]any{rows[0], rows[0], rows[2]} }),
		"unknown code":   with(func(s *histSpec) { s.rows = []map[string]any{rows[0], rows[1], {"code": "999999"}} }),
		"missing code":   with(func(s *histSpec) { s.rows = rows[:2] }),
		"extra code": with(func(s *histSpec) {
			s.rows = append(append([]map[string]any(nil), rows...), map[string]any{"code": "1"})
		}),
	}
	s := NewStore(t.TempDir())
	for name, spec := range cases {
		if _, err := s.Install("margin", testSnapshot("margin", "2026-11-18"), historyFile(t, spec)); !errors.Is(err, errInvalid) {
			t.Errorf("%s: %v", name, err)
		}
	}
	// A 20,001-row file against a snapshot of the same rows: the row limit.
	if _, err := s.Install("margin", testSnapshot("margin", "2026-11-18", manyRows...),
		historyFile(t, histSpec{module: "margin", asOf: "2026-11-18", rows: manyRows})); !errors.Is(err, errInvalid) {
		t.Errorf("row limit: %v", err)
	}
	raw := testSnapshot("margin", "2026-11-18")
	for name, history := range map[string][]byte{
		"missing":      nil,
		"empty":        {},
		"not parquet":  []byte("PAR1 this is not a parquet file"),
		"over 16 MiB":  bytes.Repeat([]byte{0}, maxHistoryBytes+1),
		"json instead": raw,
	} {
		if _, err := s.Install("margin", raw, history); !errors.Is(err, errInvalid) {
			t.Errorf("%s: %v", name, err)
		}
	}
	// Modules without rows must not carry history.
	if _, err := s.Install("sentiment", testSnapshot("sentiment", "2026-11-18"), testHistory(t, "margin", "2026-11-18")); !errors.Is(err, errInvalid) {
		t.Errorf("sentiment with history: %v", err)
	}
	for _, dir := range []string{s.root, s.histRoot} {
		if left := files(t, dir); len(left) != 0 {
			t.Errorf("a refused install left %v in %s", left, dir)
		}
	}
}

func TestInstallAcceptsTheRowLimit(t *testing.T) {
	rows := make([]map[string]any, maxHistoryRows)
	for i := range rows {
		rows[i] = map[string]any{"code": strconv.Itoa(i), "frag": float64(i)}
	}
	s := NewStore(t.TempDir())
	if _, err := s.Install("margin", testSnapshot("margin", "2026-11-18", rows...),
		historyFile(t, histSpec{module: "margin", asOf: "2026-11-18", rows: rows})); err != nil {
		t.Fatal(err)
	}
}

func TestInstallWritesGzipSnapshotsAndHistoryAndReinstallReplacesBoth(t *testing.T) {
	root := t.TempDir()
	s := NewStore(root)
	installTest(t, s, "margin", "2026-11-18")
	snapPath := filepath.Join(root, "snapshots", "margin", "2026-11-18.json.gz")
	histPath := filepath.Join(root, "history", "margin", "2026-11-18.parquet")
	raw, err := os.ReadFile(snapPath)
	if err != nil || len(raw) < 2 || raw[0] != 0x1f || raw[1] != 0x8b {
		t.Fatalf("snapshot is not gzip: %v", err)
	}
	if got := files(t, filepath.Join(root, "snapshots", "margin")); len(got) != 1 {
		t.Fatalf("snapshot dir %v", got)
	}
	zr, _ := gzip.NewReader(bytes.NewReader(raw))
	var plain bytes.Buffer
	_, _ = plain.ReadFrom(zr)
	if !bytes.Equal(plain.Bytes(), testSnapshot("margin", "2026-11-18")) {
		t.Fatal("gzip round trip changed the document")
	}
	before, _ := os.ReadFile(histPath)
	one := []map[string]any{{"code": "600000", "name": "A", "frag": 1.0}}
	installTest(t, s, "margin", "2026-11-18", one...)
	after, _ := os.ReadFile(histPath)
	if bytes.Equal(before, after) {
		t.Fatal("history not replaced by a re-run")
	}
	snap, err := s.Load("margin", "2026-11-18")
	if err != nil || len(snap.Rows) != 1 {
		t.Fatalf("snapshot not replaced: %v %v", snap, err)
	}
	for _, d := range []string{filepath.Join(root, "snapshots", "margin"), filepath.Join(root, "history", "margin")} {
		for _, name := range files(t, d) {
			if strings.HasSuffix(name, ".tmp") {
				t.Fatalf("leftover %s", name)
			}
		}
	}
}

func TestHistoryIsInstalledBeforeTheSnapshot(t *testing.T) {
	// A snapshot directory that cannot be created makes the second write
	// fail; the history file written first remains, which is the documented
	// harmless state (listed by /history/dates, replaced by the re-run).
	root := t.TempDir()
	s := NewStore(root)
	if err := os.WriteFile(filepath.Join(root, "snapshots"), []byte("x"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Install("margin", testSnapshot("margin", "2026-11-18"), testHistory(t, "margin", "2026-11-18")); err == nil {
		t.Fatal("install succeeded without a snapshot directory")
	}
	dates, _ := s.HistoryDates("margin")
	if len(dates) != 1 || dates[0] != "2026-11-18" {
		t.Fatalf("history written first: %v", dates)
	}
	if err := os.Remove(filepath.Join(root, "snapshots")); err != nil {
		t.Fatal(err)
	}
	installTest(t, s, "margin", "2026-11-18") // the re-run completes both
	if _, err := s.Load("margin", "2026-11-18"); err != nil {
		t.Fatal(err)
	}
}

func TestLoadLimitsTheDecompressedSizeAndReadsNoPlainJSON(t *testing.T) {
	root := t.TempDir()
	s := NewStore(root)
	dir := filepath.Join(root, "snapshots", "margin")
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	// A plain v1 file is neither listed nor read.
	if err := os.WriteFile(filepath.Join(dir, "2026-11-17.json"), testSnapshot("margin", "2026-11-17"), 0600); err != nil {
		t.Fatal(err)
	}
	if dates, _ := s.Dates("margin"); len(dates) != 0 {
		t.Fatalf("plain json listed: %v", dates)
	}
	if _, err := s.Load("margin", "2026-11-17"); !errors.Is(err, errNotFound) {
		t.Fatalf("plain json read: %v", err)
	}
	// 32 MiB + 1 byte decompressed is refused although it compresses to nothing.
	bomb, err := gzipBytes(bytes.Repeat([]byte(" "), maxSnapshotBytes+1))
	if err != nil || len(bomb) > 1<<20 {
		t.Fatal(err, len(bomb))
	}
	if err := os.WriteFile(filepath.Join(dir, "2026-11-18.json.gz"), bomb, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Load("margin", "2026-11-18"); !errors.Is(err, errInvalid) {
		t.Fatalf("oversized document: %v", err)
	}
	// Not gzip at all, and gzip with trailing damage.
	if err := os.WriteFile(filepath.Join(dir, "2026-11-19.json.gz"), testSnapshot("margin", "2026-11-19"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Load("margin", "2026-11-19"); !errors.Is(err, errInvalid) {
		t.Fatalf("not gzip: %v", err)
	}
}

func TestSnapshotCacheIsChargedTwiceTheDecompressedSize(t *testing.T) {
	s := NewStore(t.TempDir())
	installTest(t, s, "margin", "2026-11-18")
	if _, err := s.Load("margin", "2026-11-18"); err != nil {
		t.Fatal(err)
	}
	want := 2 * len(testSnapshot("margin", "2026-11-18"))
	if got := s.sizes["margin/2026-11-18"]; got != want || s.cachedBytes != want {
		t.Fatalf("charged %d (total %d), want %d", got, s.cachedBytes, want)
	}
	// A document whose charge exceeds the budget is not cached.
	s.cacheBudget = want - 1
	s.dropLocked("margin/2026-11-18")
	if _, err := s.Load("margin", "2026-11-18"); err != nil {
		t.Fatal(err)
	}
	if len(s.cache) != 0 {
		t.Fatal("over-budget document cached")
	}
}

func snapshotDates(t *testing.T, s *Store, module string) string {
	t.Helper()
	dates, err := s.Dates(module)
	if err != nil {
		t.Fatal(err)
	}
	return strings.Join(dates, ",")
}

func TestRetentionIsRelativeToTheModulesNewestDate(t *testing.T) {
	s := NewStore(t.TempDir())
	dates := []string{
		"2026-11-18", // newest
		"2025-11-18", // exactly 365 days before: kept
		"2025-11-17", // 366 days: removed
		"2025-01-01", // removed
	}
	for _, d := range dates {
		installTest(t, s, "margin", d)
	}
	// Another module with a much older newest date is judged on its own.
	installTest(t, s, "etf", "2024-03-01")
	installTest(t, s, "etf", "2023-03-02") // 365 days before 2024-03-01 (a leap year): kept
	installTest(t, s, "etf", "2023-03-01") // 366 days: removed
	removed := s.Retain(nil)
	if got := strings.Join(removed, ","); got != "etf/2023-03-01,margin/2025-01-01,margin/2025-11-17" {
		t.Fatalf("removed %s", got)
	}
	if got := snapshotDates(t, s, "margin"); got != "2026-11-18,2025-11-18" {
		t.Fatalf("margin %s", got)
	}
	if got := snapshotDates(t, s, "etf"); got != "2024-03-01,2023-03-02" {
		t.Fatalf("etf %s", got)
	}
	// History is never removed.
	hd, _ := s.HistoryDates("margin")
	if len(hd) != 4 {
		t.Fatalf("history removed: %v", hd)
	}
	// A removed date is no longer served from the cache either.
	if _, err := s.Load("margin", "2025-01-01"); !errors.Is(err, errNotFound) {
		t.Fatalf("removed date served: %v", err)
	}
}

func TestRetentionNeverRemovesTheNewestOrADateInstalledByTheRun(t *testing.T) {
	s := NewStore(t.TempDir())
	installTest(t, s, "margin", "2026-11-18")
	installTest(t, s, "margin", "2024-06-01") // a backfill of an old date
	installTest(t, s, "margin", "2023-06-01") // another old one, not protected
	removed := s.Retain(map[string]map[string]bool{"margin": {"2024-06-01": true}})
	if strings.Join(removed, ",") != "margin/2023-06-01" {
		t.Fatalf("removed %v", removed)
	}
	if got := snapshotDates(t, s, "margin"); got != "2026-11-18,2024-06-01" {
		t.Fatalf("dates %s", got)
	}
	// The newest snapshot is kept even when it is the only one and old.
	s2 := NewStore(t.TempDir())
	installTest(t, s2, "margin", "2020-01-01")
	if removed := s2.Retain(nil); len(removed) != 0 {
		t.Fatalf("removed the newest: %v", removed)
	}
	// Unprotected, a backfill from an earlier run goes at the next run.
	if removed := s.Retain(nil); strings.Join(removed, ",") != "margin/2024-06-01" {
		t.Fatalf("next run removed %v", removed)
	}
}

func TestRetentionLeavesPlainFilesAndStrayNamesAlone(t *testing.T) {
	root := t.TempDir()
	s := NewStore(root)
	installTest(t, s, "margin", "2026-11-18")
	dir := filepath.Join(root, "snapshots", "margin")
	for _, name := range []string{"2020-01-01.json", "notes.txt", "2020-01-02.json.gz.tmp"} {
		if err := os.WriteFile(filepath.Join(dir, name), []byte("x"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	if removed := s.Retain(nil); len(removed) != 0 {
		t.Fatalf("removed %v", removed)
	}
	for _, name := range []string{"2020-01-01.json", "notes.txt", "2020-01-02.json.gz.tmp"} {
		if !exists(filepath.Join(dir, name)) {
			t.Errorf("%s removed", name)
		}
	}
}

// stage writes a job's output directory.
func stage(t *testing.T, dir string, outputs map[string][]byte) string {
	t.Helper()
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	for name, raw := range outputs {
		if err := os.WriteFile(filepath.Join(dir, name), raw, 0600); err != nil {
			t.Fatal(err)
		}
	}
	return dir
}

func nop(string, ...any) {}

func TestInstallOutputsNeedsAValidHistoryFileForEveryRowModule(t *testing.T) {
	data := t.TempDir()
	store := NewStore(data)
	r, err := NewRunner(data, nil, store)
	if err != nil {
		t.Fatal(err)
	}
	snap := testSnapshot("margin", "2026-11-18")
	hist := testHistory(t, "margin", "2026-11-18")
	sentiment := testSnapshot("sentiment", "2026-11-18")
	cases := map[string]map[string][]byte{
		"history missing":          {"margin.json": snap, "sentiment.json": sentiment},
		"history invalid":          {"margin.json": snap, "margin.history.parquet": []byte("nope"), "sentiment.json": sentiment},
		"history of another date":  {"margin.json": testSnapshot("margin", "2026-11-17"), "margin.history.parquet": hist, "sentiment.json": sentiment},
		"history without snapshot": {"margin.history.parquet": hist, "sentiment.json": sentiment},
		"history for sentiment":    {"margin.json": snap, "margin.history.parquet": hist, "sentiment.json": sentiment, "sentiment.history.parquet": hist},
		"unexpected file":          {"margin.json": snap, "margin.history.parquet": hist, "sentiment.json": sentiment, "notes.txt": []byte("x")},
		"a leftover tmp file":      {"margin.json": snap, "margin.history.parquet": hist, "margin.history.parquet.tmp": hist, "sentiment.json": sentiment},
	}
	for name, outputs := range cases {
		installed, err := r.installOutputs(stage(t, filepath.Join(t.TempDir(), "s"), outputs), nop)
		if err == nil || len(installed) != 0 {
			t.Errorf("%s: installed %v, err %v", name, installed, err)
		}
	}
	// Validation comes first: nothing from any refused run was installed,
	// not even the valid sentiment output that sat beside the bad one.
	for _, m := range []string{"margin", "sentiment"} {
		if dates, _ := store.Dates(m); len(dates) != 0 {
			t.Errorf("%s installed %v", m, dates)
		}
	}
	if dates, _ := store.HistoryDates("margin"); len(dates) != 0 {
		t.Errorf("history installed %v", dates)
	}
	// And the valid set installs all of it.
	installed, err := r.installOutputs(stage(t, filepath.Join(t.TempDir(), "s"), map[string][]byte{
		"margin.json": snap, "margin.history.parquet": hist, "sentiment.json": sentiment}), nop)
	if err != nil || strings.Join(installed, ",") != "margin/2026-11-18,sentiment/2026-11-18" {
		t.Fatalf("%v %v", installed, err)
	}
}

func TestRunFailsAsOutputInvalidWhenHistoryIsMissing(t *testing.T) {
	data, scripts := t.TempDir(), t.TempDir()
	src := filepath.Join(scripts, "snap.json")
	if err := os.WriteFile(src, testSnapshot("margin", "2026-11-18"), 0600); err != nil {
		t.Fatal(err)
	}
	spec := scriptJob(t, scripts, "margin", "#!/bin/sh\ncp '"+src+"' \"$MM_OUTPUT_DIR/margin.json\"\n", 10*time.Second)
	store := NewStore(data)
	r, _ := NewRunner(data, []JobSpec{spec}, store)
	stop := r.Start()
	defer stop()
	run, _, _ := r.Submit("margin", "t1", "run:1")
	done := waitRun(t, r, run.ID)
	if done.Status != "failed" || done.Error != "output_invalid" {
		t.Fatalf("run %+v", done)
	}
	if dates, _ := store.Dates("margin"); len(dates) != 0 {
		t.Fatalf("installed %v", dates)
	}
	log, _ := os.ReadFile(filepath.Join(data, "runs", run.ID+".log"))
	if !strings.Contains(string(log), "history file missing") {
		t.Fatalf("reason not logged: %q", log)
	}
}

func TestInstallOutputsRetentionProtectsThisRunsDatesOnly(t *testing.T) {
	data := t.TempDir()
	store := NewStore(data)
	r, _ := NewRunner(data, nil, store)
	run := func(date string) []string {
		installed, err := r.installOutputs(stage(t, filepath.Join(t.TempDir(), "s"), map[string][]byte{
			"margin.json": testSnapshot("margin", date), "margin.history.parquet": testHistory(t, "margin", date)}), nop)
		if err != nil {
			t.Fatal(err)
		}
		return installed
	}
	run("2026-11-18")
	run("2024-01-01") // a backfill: this run installed it, so it survives
	if got := snapshotDates(t, store, "margin"); got != "2026-11-18,2024-01-01" {
		t.Fatalf("after the backfill run: %s", got)
	}
	run("2026-11-19") // the next run no longer protects it
	if got := snapshotDates(t, store, "margin"); got != "2026-11-19,2026-11-18" {
		t.Fatalf("after the next run: %s", got)
	}
	if hd, _ := store.HistoryDates("margin"); len(hd) != 3 {
		t.Fatalf("history %v", hd)
	}
}

func TestQuotaWarningAtEightyPercent(t *testing.T) {
	saved := fsUsage
	defer func() { fsUsage = saved }()
	for _, c := range []struct {
		used, total uint64
		warn        bool
	}{{79, 100, false}, {80, 100, true}, {100, 100, true}, {0, 0, false}} {
		fsUsage = func(string) (uint64, uint64, error) { return c.used << 30, c.total << 30, nil }
		if got := quotaWarning("/data") != ""; got != c.warn {
			t.Errorf("%d of %d: warning %v", c.used, c.total, got)
		}
	}
	fsUsage = func(string) (uint64, uint64, error) { return 0, 0, errors.New("no statfs") }
	if quotaWarning("/data") != "" {
		t.Error("warned without a reading")
	}
	fsUsage = func(string) (uint64, uint64, error) { return 5 << 30, 6 << 30, nil }
	if msg := quotaWarning("/data"); !strings.Contains(msg, "83 %") || !strings.Contains(msg, "6144 MiB") {
		t.Errorf("message %q", msg)
	}
}

func TestRunnerChecksTheQuotaAfterEveryRun(t *testing.T) {
	data, scripts := t.TempDir(), t.TempDir()
	r, _ := NewRunner(data, []JobSpec{fakeJob(t, scripts, "margin", string(testSnapshot("margin", "2026-11-18")), 0)}, NewStore(data))
	calls := make(chan struct{}, 4)
	r.afterRun = func() { calls <- struct{}{} }
	stop := r.Start()
	defer stop()
	run, _, _ := r.Submit("margin", "t1", "run:1")
	waitRun(t, r, run.ID)
	select {
	case <-calls:
	case <-time.After(5 * time.Second):
		t.Fatal("quota not checked")
	}
}

// heapGrowth runs f and returns how many bytes this process allocated meanwhile.
func heapGrowth(f func()) uint64 {
	var before, after runtime.MemStats
	runtime.GC()
	runtime.ReadMemStats(&before)
	f()
	runtime.ReadMemStats(&after)
	return after.TotalAlloc - before.TotalAlloc
}

const crafted = "testdata/crafted"

// The two crafted files are single-byte corruptions of real history files:
// the first switches a column's codec to LZ4 (whose decoder grew past 1 GiB),
// the second makes the thrift page-header decode allocate 802 MB.
var craftedFiles = []struct{ name, module string }{
	{"lz4-bomb-margin.parquet", "margin"},
	{"page-header-etf.parquet", "etf"},
}

func craftedRows(module string) []map[string]any {
	if module == "etf" {
		return []map[string]any{{"code": "588000"}, {"code": "510300"}}
	}
	return []map[string]any{{"code": "600000"}, {"code": "000001"}, {"code": "300001"}}
}

func TestCraftedHistoryFilesAreRefusedOnTheReadPathWithoutDecoding(t *testing.T) {
	for _, c := range craftedFiles {
		raw, err := os.ReadFile(filepath.Join(crafted, c.name))
		if err != nil {
			t.Fatal(err)
		}
		s := NewStore(t.TempDir())
		dir := filepath.Join(s.histRoot, c.module)
		if err := os.MkdirAll(dir, 0700); err != nil {
			t.Fatal(err)
		}
		path := filepath.Join(dir, "2026-11-16"+historySuffix)
		if err := os.WriteFile(path, raw, 0600); err != nil { // no sidecar
			t.Fatal(err)
		}
		q, done, _ := s.beginHistory()
		var loadErr error
		grown := heapGrowth(func() { _, loadErr = q.load(c.module, "2026-11-16") })
		done()
		if !errors.Is(loadErr, errInvalid) || !strings.Contains(loadErr.Error(), "sidecar missing") {
			t.Errorf("%s without a sidecar: %v", c.name, loadErr)
		}
		// A sidecar for some other file (here the pristine fixture's) does not match.
		good, _ := os.ReadFile(filepath.Join("testdata", "pyarrow", c.module+".history.parquet"))
		sum := sha256.Sum256(good)
		if err := os.WriteFile(path+historySidecarSuffix, []byte(hex.EncodeToString(sum[:])), 0600); err != nil {
			t.Fatal(err)
		}
		q, done, _ = s.beginHistory()
		grown += heapGrowth(func() { _, loadErr = q.load(c.module, "2026-11-16") })
		done()
		if !errors.Is(loadErr, errInvalid) || !strings.Contains(loadErr.Error(), "mismatch") {
			t.Errorf("%s with a wrong sidecar: %v", c.name, loadErr)
		}
		if grown > 8<<20 {
			t.Errorf("%s: the refusal allocated %d bytes", c.name, grown)
		}
		// Through the API it is 409 unavailable, never a parse.
		if len(s.hist.warned) != 2 { // one entry per reason
			t.Errorf("refusals not logged once each: %v", s.hist.warned)
		}
	}
}

func TestCraftedHistoryFilesAreRefusedOnTheInstallPath(t *testing.T) {
	for _, c := range craftedFiles {
		raw, err := os.ReadFile(filepath.Join(crafted, c.name))
		if err != nil {
			t.Fatal(err)
		}
		s := NewStore(t.TempDir())
		var installErr error
		grown := heapGrowth(func() {
			_, installErr = s.Install(c.module, testSnapshot(c.module, "2026-11-16", craftedRows(c.module)...), raw)
		})
		if !errors.Is(installErr, errInvalid) {
			t.Errorf("%s: %v", c.name, installErr)
		}
		if grown > 16<<20 {
			t.Errorf("%s: the parent allocated %d bytes", c.name, grown)
		}
		for _, dir := range []string{s.root, s.histRoot} {
			if left := files(t, dir); len(left) != 0 {
				t.Errorf("%s left %v", c.name, left)
			}
		}
	}
}

func TestHistoryCodecAllowlist(t *testing.T) {
	spec := histSpec{module: "etf", asOf: "2026-11-16", rows: craftedRows("etf")}
	for name, codec := range map[string]compress.Codec{"snappy": &snappy.Codec{}, "gzip": &pgzip.Codec{}, "lz4": &lz4.Codec{}} {
		raw := historyFileWithCodec(t, spec, codec)
		if _, err := parseHistory("etf", "2026-11-16", raw); !errors.Is(err, errInvalid) {
			t.Errorf("%s accepted: %v", name, err)
		}
	}
	for name, codec := range map[string]compress.Codec{"zstd": &zstd.Codec{}, "uncompressed": &uncompressed.Codec{}} {
		if _, err := parseHistory("etf", "2026-11-16", historyFileWithCodec(t, spec, codec)); err != nil {
			t.Errorf("%s refused: %v", name, err)
		}
	}
}

func TestInstallRefusesAFarFutureDate(t *testing.T) {
	s := NewStore(t.TempDir())
	s.now = func() time.Time { return time.Date(2026, 11, 20, 3, 0, 0, 0, time.UTC) }
	install := func(date string) error {
		_, err := s.Install("margin", testSnapshot("margin", date), testHistory(t, "margin", date))
		return err
	}
	if err := install("2026-11-23"); err != nil { // three days ahead is accepted
		t.Fatal(err)
	}
	if err := install("2026-11-24"); !errors.Is(err, errInvalid) {
		t.Fatalf("four days ahead: %v", err)
	}
	if err := install("2099-01-01"); !errors.Is(err, errInvalid) {
		t.Fatalf("far future: %v", err)
	}
	if _, err := s.Install("sentiment", testSnapshot("sentiment", "2099-01-01"), nil); !errors.Is(err, errInvalid) {
		t.Fatalf("far future sentiment: %v", err)
	}
	// And it never reached retention: the only snapshot is the legitimate one.
	if got := snapshotDates(t, s, "margin"); got != "2026-11-23" {
		t.Fatalf("dates %s", got)
	}
}

func TestInstallWritesTheIntegritySidecarAndListingIgnoresIt(t *testing.T) {
	root := t.TempDir()
	s := NewStore(root)
	installTest(t, s, "margin", "2026-11-18")
	dir := filepath.Join(root, "history", "margin")
	data, _ := os.ReadFile(filepath.Join(dir, "2026-11-18.parquet"))
	side, err := os.ReadFile(filepath.Join(dir, "2026-11-18.parquet.sha256"))
	sum := sha256.Sum256(data)
	if err != nil || strings.TrimSpace(string(side)) != hex.EncodeToString(sum[:]) {
		t.Fatalf("sidecar %q %v", side, err)
	}
	if dates, _ := s.HistoryDates("margin"); len(dates) != 1 {
		t.Fatalf("sidecar listed as a date: %v", dates)
	}
	// A missing sidecar makes the date unavailable, not unparsed.
	if err := os.Remove(filepath.Join(dir, "2026-11-18.parquet.sha256")); err != nil {
		t.Fatal(err)
	}
	s.hist.drop("margin/2026-11-18")
	q, done, _ := s.beginHistory()
	defer done()
	if _, err := q.load("margin", "2026-11-18"); !errors.Is(err, errInvalid) {
		t.Fatalf("no sidecar: %v", err)
	}
}

// runChild runs the validate-history child mode of the test binary as a
// subprocess (never in-process: it caps the address space of its process).
func runChild(t *testing.T, module, asOf string, data []byte) (int, string, string) {
	t.Helper()
	cmd := exec.Command(os.Args[0], validateHistoryArg, module, asOf)
	var out, errOut bytes.Buffer
	cmd.Stdin, cmd.Stdout, cmd.Stderr = bytes.NewReader(data), &out, &errOut
	cmd.Env = []string{}
	err := cmd.Run()
	code := 0
	if err != nil {
		var exit *exec.ExitError
		if !errors.As(err, &exit) {
			t.Fatal(err)
		}
		code = exit.ExitCode()
	}
	return code, out.String(), errOut.String()
}

func TestValidatorChildFailuresAreMappedToTheRightVerdict(t *testing.T) {
	saved := historyChildCommand
	defer func() { historyChildCommand = saved }()
	hist := testHistory(t, "margin", "2026-11-18")
	sh := func(script string) func(context.Context, string, string) (*exec.Cmd, error) {
		return func(ctx context.Context, _, _ string) (*exec.Cmd, error) {
			return exec.CommandContext(ctx, "/bin/sh", "-c", script), nil
		}
	}
	// A verdict on the file: output_invalid.
	for name, command := range map[string]func(context.Context, string, string) (*exec.Cmd, error){
		"bad file exit": sh("exit 1"),
		"runtime fatal": sh("exit 2"),
		"wrong report":  sh("echo ok 3 abc"),
		"no report":     sh("true"),
	} {
		historyChildCommand = command
		_, err := NewStore(t.TempDir()).Install("margin", testSnapshot("margin", "2026-11-18"), hist)
		if !errors.Is(err, errInvalid) || errors.Is(err, errValidatorUnavailable) {
			t.Errorf("%s: %v", name, err)
		}
	}
	// The machinery failing: validator_unavailable, never a verdict on the file.
	for name, command := range map[string]func(context.Context, string, string) (*exec.Cmd, error){
		"environment exit": sh("exit 3"),
		"usage exit":       sh("exit 4"),
		"killed by signal": sh("kill -9 $$"),
		"cannot find exe":  func(context.Context, string, string) (*exec.Cmd, error) { return nil, errors.New("no executable") },
		"cannot start": func(ctx context.Context, _, _ string) (*exec.Cmd, error) {
			return exec.CommandContext(ctx, "/nonexistent/child"), nil
		},
	} {
		historyChildCommand = command
		_, err := NewStore(t.TempDir()).Install("margin", testSnapshot("margin", "2026-11-18"), hist)
		if !errors.Is(err, errValidatorUnavailable) || errors.Is(err, errInvalid) {
			t.Errorf("%s: %v", name, err)
		}
	}
	// A child that hangs is killed at the timeout, which is the file's verdict.
	historyChildCommand = sh("sleep 30")
	start := time.Now()
	if _, err := NewStore(t.TempDir()).Install("margin", testSnapshot("margin", "2026-11-18"), hist); !errors.Is(err, errInvalid) || !strings.Contains(err.Error(), "timed out") {
		t.Errorf("hang: %v", err)
	}
	if time.Since(start) > historyChildTimeout+5*time.Second {
		t.Errorf("timeout took %s", time.Since(start))
	}
}

func TestRunReportsValidatorUnavailableApartFromOutputInvalid(t *testing.T) {
	saved := historyChildCommand
	defer func() { historyChildCommand = saved }()
	run := func(history []byte) Run {
		data, scripts := t.TempDir(), t.TempDir()
		src := filepath.Join(scripts, "snap.json")
		hist := filepath.Join(scripts, "snap.history.parquet")
		if err := os.WriteFile(src, testSnapshot("margin", "2026-11-18"), 0600); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(hist, history, 0600); err != nil {
			t.Fatal(err)
		}
		spec := scriptJob(t, scripts, "margin", "#!/bin/sh\ncp '"+src+"' \"$MM_OUTPUT_DIR/margin.json\"\ncp '"+hist+"' \"$MM_OUTPUT_DIR/margin.history.parquet\"\n", 20*time.Second)
		r, _ := NewRunner(data, []JobSpec{spec}, NewStore(data))
		stop := r.Start()
		defer stop()
		run, _, _ := r.Submit("margin", "t1", "run:1")
		done := waitRun(t, r, run.ID)
		if done.Status != "failed" {
			t.Fatalf("run %+v", done)
		}
		return done
	}
	good := testHistory(t, "margin", "2026-11-18")
	historyChildCommand = func(ctx context.Context, _, _ string) (*exec.Cmd, error) {
		return exec.CommandContext(ctx, "/bin/sh", "-c", "exit 3"), nil
	}
	if got := run(good); got.Error != "validator_unavailable" {
		t.Fatalf("environment fault reported as %q", got.Error)
	}
	historyChildCommand = saved
	crafted, _ := os.ReadFile(filepath.Join("testdata", "crafted", "lz4-bomb-margin.parquet"))
	if got := run(crafted); got.Error != "output_invalid" {
		t.Fatalf("bad file reported as %q", got.Error)
	}
	if got := run([]byte("not parquet")); got.Error != "output_invalid" {
		t.Fatalf("bad file reported as %q", got.Error)
	}
}

func TestValidatorChildDecodesEveryColumn(t *testing.T) {
	// A file whose code column is fine but whose other column cannot be
	// decoded: corrupt the data pages of the last column only.
	good, _ := os.ReadFile(filepath.Join("testdata", "pyarrow", "margin.history.parquet"))
	f, _ := parseHistory("margin", "2026-11-16", good)
	cols := f.Metadata().RowGroups[0].Columns
	last := cols[len(cols)-1].MetaData // the tags column
	broken := append([]byte(nil), good...)
	for i := last.DataPageOffset + 16; i < last.DataPageOffset+last.TotalCompressedSize-8 && i < int64(len(broken)); i++ {
		broken[i] ^= 0xff
	}
	if code, out, _ := runChild(t, "margin", "2026-11-16", broken); code == 0 {
		t.Fatalf("a corrupt non-code column was accepted: %s", out)
	}
	if code, out, errOut := runChild(t, "margin", "2026-11-16", good); code != 0 || !strings.HasPrefix(out, "ok 3 ") {
		t.Fatalf("good file: %d %s %s", code, out, errOut)
	}
	// Usage errors are the environment's, not a verdict.
	if code, _, _ := runChild(t, "margin", "not-a-date", good); code != exitUsage {
		t.Fatalf("usage exit %d", code)
	}
}

func TestRefusalsAreLoggedOncePerFileVersionAndReason(t *testing.T) {
	h := newHistoryState()
	a, b := fileID{ino: 1, size: 10}, fileID{ino: 2, size: 10}
	e1, e2 := errors.New("sidecar missing"), errors.New("sidecar mismatch")
	var logged bytes.Buffer
	log.SetOutput(&logged)
	defer log.SetOutput(os.Stderr)
	for _, c := range []struct {
		id  fileID
		err error
	}{{a, e1}, {a, e1}, {b, e1}, {b, e2}, {b, e2}} {
		h.warnOnce("/x/2026-11-16.parquet", c.id, c.err)
	}
	if n := strings.Count(logged.String(), "refused"); n != 3 {
		t.Fatalf("%d log lines:\n%s", n, logged.String())
	}
	// The set is bounded.
	for i := 0; i < 3*maxWarned; i++ {
		h.warnOnce("/nonexistent/"+strconv.Itoa(i), a, e1)
	}
	if len(h.warned) > maxWarned {
		t.Fatalf("%d entries", len(h.warned))
	}
}
