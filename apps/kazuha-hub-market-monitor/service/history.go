package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"log"
	"math"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/parquet-go/parquet-go"
	"github.com/parquet-go/parquet-go/format"
)

// History files (docs/store-v2.md): one parquet file per module and as-of
// date with a fixed, curated set of columns, written by mm_job.py. The
// service refuses a file whose column names and types are not exactly the
// module's schema, and checks the key-value metadata against the path on
// install and on every read.

const (
	historyFormat   = "market-monitor.history/1"
	historySuffix   = ".parquet"
	maxHistoryRows  = 20000
	maxHistoryBytes = 16 << 20
	// A zstd file of at most 16 MiB can describe far more data than that;
	// the footer's own uncompressed sizes are checked before any column is
	// decoded. About 250 times the real Panorama file.
	maxHistoryUncompressed = 128 << 20
	// Per column chunk: a real 20,000-row chunk is far below this.
	maxChunkUncompressed = 32 << 20
	historySidecarSuffix = ".sha256"
	// A re-run of a date can show a reader the new sidecar with the old file
	// for the span of two renames; one retry after this pause covers it.
	historyRetryBackoff = 50 * time.Millisecond
	maxWarned           = 256

	historyCacheBudget = 64 << 20
	// A query over more files than this reads without the cache, so one long
	// scan does not evict the working set.
	historyCacheMaxScan = 60
	queryTimeout        = 4 * time.Second
)

type histCol struct {
	name string
	str  bool // a string column; otherwise double
}

func strCols(names ...string) []histCol {
	out := make([]histCol, len(names))
	for i, n := range names {
		out[i] = histCol{n, true}
	}
	return out
}

func numCols(names ...string) []histCol {
	out := make([]histCol, len(names))
	for i, n := range names {
		out[i] = histCol{n, false}
	}
	return out
}

func joinCols(parts ...[]histCol) []histCol {
	var out []histCol
	for _, p := range parts {
		out = append(out, p...)
	}
	return out
}

// historySchemas is market-monitor.history/1, in file order. A schema change
// is a new format version with a reader for both, never an edit of this table.
var historySchemas = map[string][]histCol{
	"margin": joinCols(strCols("code", "name"),
		numCols("price", "chg", "rz", "ratio", "dratio20", "rz_chg5", "rz_chg20", "buf_call", "buf_liq", "pnl", "score", "frag"),
		strCols("state", "level", "tags")),
	"panorama": joinCols(strCols("code", "name", "sw1"),
		numCols("price", "mktcap", "pe", "pb", "roe", "upside"),
		strCols("label", "quad", "profile"),
		numCols("s_value", "s_growth", "s_cyclical", "s_dividend", "s_momentum", "s_quality")),
	"etf": joinCols(strCols("code", "name", "cat"), numCols("cum_ytd", "cum20")),
}

// historyModules are the modules that have rows, and so history.
var historyModules = map[string]bool{"margin": true, "panorama": true, "etf": true}

func historyColumn(module, name string) (histCol, int, bool) {
	for i, c := range historySchemas[module] {
		if c.name == name {
			return c, i, true
		}
	}
	return histCol{}, -1, false
}

// colData is one decoded column, immutable once built so a query can keep
// reading it after the cache has evicted its file.
type colData struct {
	str []string  // string column
	num []float64 // double column
	ok  []bool    // false where the value is null
}

func (c *colData) size() int {
	n := len(c.ok) * (1 + 16)
	n += len(c.num) * 8
	for _, s := range c.str {
		n += len(s)
	}
	return n
}

// histView is what a query sees of one file: its row count and the requested
// columns (code always among them).
type histView struct {
	rows int
	cols map[string]*colData
}

func (v *histView) code(i int) string { return v.cols["code"].str[i] }

// string returns a string column's value, ok false for null.
func (v *histView) str(col string, i int) (string, bool) {
	c := v.cols[col]
	return c.str[i], c.ok[i]
}

func (v *histView) num(col string, i int) (float64, bool) {
	c := v.cols[col]
	return c.num[i], c.ok[i]
}

// fileID identifies the file content a cache entry was read from.
type fileID struct {
	dev, ino uint64
	size     int64
	mtime    int64
}

func idOf(st os.FileInfo) fileID {
	id := fileID{size: st.Size(), mtime: st.ModTime().UnixNano()}
	if sys, ok := st.Sys().(*syscall.Stat_t); ok {
		id.dev, id.ino = uint64(sys.Dev), uint64(sys.Ino) //nolint:unconvert // widths differ by platform
	}
	return id
}

type histEntry struct {
	id    fileID
	cols  map[string]*colData
	bytes int
}

// historyState is the history cache and the one-query-at-a-time gate.
type historyState struct {
	mu     sync.Mutex
	cache  map[string]*histEntry
	order  []string // least recently used first
	bytes  int
	budget int
	gate   chan struct{}
	warned map[warnKey]bool

	// Test hooks.
	timeout    time.Duration
	beforeFile func(path string)
}

func newHistoryState() *historyState {
	return &historyState{cache: map[string]*histEntry{}, budget: historyCacheBudget,
		gate: make(chan struct{}, 1), warned: map[warnKey]bool{}, timeout: queryTimeout}
}

func (h *historyState) dropLocked(key string) {
	e, ok := h.cache[key]
	if !ok {
		return
	}
	h.bytes -= e.bytes
	delete(h.cache, key)
	for i, k := range h.order {
		if k == key {
			h.order = append(h.order[:i:i], h.order[i+1:]...)
			break
		}
	}
}

func (h *historyState) drop(key string) {
	h.mu.Lock()
	h.dropLocked(key)
	h.mu.Unlock()
}

func (h *historyState) touchLocked(key string) {
	for i, k := range h.order {
		if k == key {
			h.order = append(append(h.order[:i:i], h.order[i+1:]...), key)
			return
		}
	}
}

// lookup returns the cached columns when the entry still describes the file
// at path (checked with stat on every use) and holds every named column.
func (h *historyState) lookup(key string, id fileID, names []string) (*histView, bool) {
	h.mu.Lock()
	defer h.mu.Unlock()
	e, ok := h.cache[key]
	if !ok {
		return nil, false
	}
	if e.id != id {
		h.dropLocked(key)
		return nil, false
	}
	view := &histView{cols: map[string]*colData{}}
	for _, n := range names {
		c, ok := e.cols[n]
		if !ok {
			return nil, false
		}
		view.cols[n] = c
	}
	view.rows = len(e.cols["code"].ok)
	h.touchLocked(key)
	return view, true
}

// store records freshly read columns under the identity of the file they
// were read from. A different identity replaces the entry.
func (h *historyState) store(key string, id fileID, cols map[string]*colData) {
	h.mu.Lock()
	defer h.mu.Unlock()
	e := h.cache[key]
	if e != nil && e.id != id {
		h.dropLocked(key)
		e = nil
	}
	if e == nil {
		e = &histEntry{id: id, cols: map[string]*colData{}}
	} else {
		h.bytes -= e.bytes
		h.touchLocked(key)
	}
	for n, c := range cols {
		e.cols[n] = c
	}
	e.bytes = 0
	for _, c := range e.cols {
		e.bytes += c.size()
	}
	if e.bytes > h.budget {
		delete(h.cache, key)
		for i, k := range h.order {
			if k == key {
				h.order = append(h.order[:i:i], h.order[i+1:]...)
				break
			}
		}
		return
	}
	if _, present := h.cache[key]; !present {
		h.order = append(h.order, key)
	}
	h.cache[key] = e
	h.bytes += e.bytes
	for h.bytes > h.budget && len(h.order) > 1 {
		h.dropLocked(h.order[0])
	}
}

// parseHistory opens a history file from memory and checks everything that
// does not need the column data: size, row count, footer sizes, exact schema
// and the metadata against the module and date. A malformed file may make the
// parquet library panic; that is reported as an invalid file.
func parseHistory(module, asOf string, data []byte) (f *parquet.File, err error) {
	defer func() {
		if r := recover(); r != nil {
			f, err = nil, fmt.Errorf("%w: history file: %v", errInvalid, r)
		}
	}()
	if len(data) == 0 || len(data) > maxHistoryBytes {
		return nil, fmt.Errorf("%w: history size", errInvalid)
	}
	f, err = parquet.OpenFile(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return nil, fmt.Errorf("%w: history file: %v", errInvalid, err)
	}
	if f.NumRows() > maxHistoryRows {
		return nil, fmt.Errorf("%w: history has %d rows", errInvalid, f.NumRows())
	}
	var rows, uncompressed int64
	size := int64(len(data))
	for _, rg := range f.Metadata().RowGroups {
		rows += rg.NumRows
		if rg.NumRows < 0 || rg.NumRows > maxHistoryRows {
			return nil, fmt.Errorf("%w: history row group size", errInvalid)
		}
		for _, c := range rg.Columns {
			m := c.MetaData
			// Only codecs the writer uses are accepted, so a flipped codec
			// byte cannot reach a decompressor that grows without bound; and
			// every size and offset the footer claims must fit the file.
			if m.Codec != format.Zstd && m.Codec != format.Uncompressed {
				return nil, fmt.Errorf("%w: history codec %v", errInvalid, m.Codec)
			}
			start := m.DataPageOffset
			if m.DictionaryPageOffset > 0 && m.DictionaryPageOffset < start {
				start = m.DictionaryPageOffset
			}
			if c.FilePath != "" || m.NumValues < 0 || m.NumValues > maxHistoryRows || m.NumValues != rg.NumRows ||
				m.TotalUncompressedSize < 0 || m.TotalUncompressedSize > maxChunkUncompressed ||
				m.TotalCompressedSize < 0 || m.TotalCompressedSize > size ||
				m.DataPageOffset < 4 || m.DataPageOffset >= size || (m.DictionaryPageOffset != 0 && m.DictionaryPageOffset < 4) ||
				start < 4 || start+m.TotalCompressedSize > size {
				return nil, fmt.Errorf("%w: history column chunk bounds", errInvalid)
			}
			uncompressed += m.TotalUncompressedSize
		}
	}
	if rows != f.NumRows() || uncompressed < 0 || uncompressed > maxHistoryUncompressed {
		return nil, fmt.Errorf("%w: history sizes", errInvalid)
	}
	if err := checkHistorySchema(module, f); err != nil {
		return nil, err
	}
	for key, want := range map[string]string{"format": historyFormat, "module": module, "as_of": asOf} {
		if got, ok := f.Lookup(key); !ok || got != want {
			return nil, fmt.Errorf("%w: history metadata %s", errInvalid, key)
		}
	}
	return f, nil
}

func checkHistorySchema(module string, f *parquet.File) error {
	want := historySchemas[module]
	cols := f.Root().Columns()
	if len(cols) != len(want) {
		return fmt.Errorf("%w: history has %d columns, want %d", errInvalid, len(cols), len(want))
	}
	for i, c := range cols {
		w := want[i]
		if c.Name() != w.name || !c.Leaf() || !c.Optional() {
			return fmt.Errorf("%w: history column %d is %q, want optional %q", errInvalid, i, c.Name(), w.name)
		}
		t := c.Type()
		logical := t.LogicalType()
		if w.str {
			isString := false
			if logical != nil {
				_, isString = logical.Value.(*format.StringType)
			}
			if t.Kind() != parquet.ByteArray || !isString {
				return fmt.Errorf("%w: history column %q is not a string", errInvalid, w.name)
			}
		} else if t.Kind() != parquet.Double || (logical != nil && logical.Value != nil) {
			return fmt.Errorf("%w: history column %q is not a double", errInvalid, w.name)
		}
	}
	return nil
}

// readColumns decodes the named columns of a validated file. Doubles that
// are not finite read as null, so a response can always be encoded.
func readColumns(module string, f *parquet.File, names []string) (cols map[string]*colData, err error) {
	defer func() {
		if r := recover(); r != nil {
			cols, err = nil, fmt.Errorf("%w: history column: %v", errInvalid, r)
		}
	}()
	cols = map[string]*colData{}
	total := int(f.NumRows())
	for _, name := range names {
		spec, idx, ok := historyColumn(module, name)
		if !ok {
			return nil, fmt.Errorf("%w: column %q", errInvalid, name)
		}
		c := &colData{ok: make([]bool, 0, total)}
		if spec.str {
			c.str = make([]string, 0, total)
		} else {
			c.num = make([]float64, 0, total)
		}
		buf := make([]parquet.Value, 1024)
		for _, rg := range f.RowGroups() {
			pages := rg.ColumnChunks()[idx].Pages()
			for {
				page, perr := pages.ReadPage()
				if perr == io.EOF {
					break
				}
				if perr != nil {
					pages.Close()
					return nil, fmt.Errorf("%w: history page: %v", errInvalid, perr)
				}
				values := page.Values()
				for {
					n, rerr := values.ReadValues(buf)
					for _, v := range buf[:n] {
						if len(c.ok) >= total {
							parquet.Release(page)
							pages.Close()
							return nil, fmt.Errorf("%w: more values than rows", errInvalid)
						}
						valid := !v.IsNull()
						if spec.str {
							s := ""
							if valid {
								s = string(v.ByteArray())
							}
							c.str = append(c.str, s)
						} else {
							x := 0.0
							if valid {
								x = v.Double()
								if math.IsNaN(x) || math.IsInf(x, 0) {
									x, valid = 0, false
								}
							}
							c.num = append(c.num, x)
						}
						c.ok = append(c.ok, valid)
					}
					if rerr == io.EOF {
						break
					}
					if rerr != nil {
						parquet.Release(page)
						pages.Close()
						return nil, fmt.Errorf("%w: history values: %v", errInvalid, rerr)
					}
				}
				parquet.Release(page)
			}
			pages.Close()
		}
		if len(c.ok) != total {
			return nil, fmt.Errorf("%w: column %q has %d values for %d rows", errInvalid, name, len(c.ok), total)
		}
		cols[name] = c
	}
	return cols, nil
}

// HistoryDates lists a module's history dates, newest first.
func (s *Store) HistoryDates(module string) ([]string, error) {
	if !historyModules[module] {
		return nil, errNotFound
	}
	return listDates(filepath.Join(s.histRoot, module), historySuffix)
}

var (
	errBusy    = errors.New("another history query is running")
	errTimeout = errors.New("history query timed out")
)

// historyQuery is one admitted query: it holds the gate and a deadline.
type historyQuery struct {
	s        *Store
	deadline time.Time
	// Reads of more than historyCacheMaxScan files bypass the cache.
	useCache bool
}

// beginHistory admits one query at a time; another arriving meanwhile gets
// errBusy. On one CPU two concurrent scans would only both time out.
func (s *Store) beginHistory() (*historyQuery, func(), error) {
	select {
	case s.hist.gate <- struct{}{}:
	default:
		return nil, nil, errBusy
	}
	q := &historyQuery{s: s, deadline: time.Now().Add(s.hist.timeout), useCache: true}
	return q, func() { <-s.hist.gate }, nil
}

// planScan declares how many files the query will read.
func (q *historyQuery) planScan(files int) { q.useCache = files <= historyCacheMaxScan }

// load returns the named columns (code is always included) of one history
// file. The deadline is checked first, so a query stops between files.
func (q *historyQuery) load(module, date string, names ...string) (*histView, error) {
	h := q.s.hist
	if time.Now().After(q.deadline) {
		return nil, errTimeout
	}
	path := filepath.Join(q.s.histRoot, module, date+historySuffix)
	if h.beforeFile != nil {
		h.beforeFile(path)
	}
	want := append([]string{"code"}, names...)
	key := module + "/" + date
	if q.useCache {
		st, err := os.Stat(path)
		if errors.Is(err, os.ErrNotExist) {
			h.drop(key)
			return nil, errNotFound
		}
		if err != nil {
			return nil, err
		}
		if view, ok := h.lookup(key, idOf(st), want); ok {
			return view, nil
		}
	}
	// Read everything needed from the file as it is now. The identity comes
	// from the open handle, so it describes the bytes decoded here even if an
	// install renames a new file over the path meanwhile.
	st, data, err := readVerified(h, path)
	if err != nil {
		return nil, err
	}
	f, err := parseHistory(module, date, data)
	if err != nil {
		return nil, err
	}
	cols, err := readColumns(module, f, dedupe(want))
	if err != nil {
		return nil, err
	}
	if q.useCache {
		h.store(key, idOf(st), cols)
	}
	return &histView{rows: int(f.NumRows()), cols: cols}, nil
}

// readVerified opens a history file and returns its identity and bytes after
// checking them against the sidecar written at install. Nothing is parsed
// before the hash matches, so only files the installer validated are ever
// decoded here. An install can replace both files between the two reads; one
// retry covers that, a second mismatch is reported.
func readVerified(h *historyState, path string) (os.FileInfo, []byte, error) {
	var lastErr error
	var id fileID
	for attempt := 0; attempt < 2; attempt++ {
		if attempt > 0 {
			time.Sleep(historyRetryBackoff)
		}
		file, err := os.Open(path)
		if errors.Is(err, os.ErrNotExist) {
			return nil, nil, errNotFound
		}
		if err != nil {
			return nil, nil, err
		}
		st, err := file.Stat()
		if err != nil {
			file.Close()
			return nil, nil, err
		}
		id = idOf(st)
		if st.Size() > maxHistoryBytes {
			file.Close()
			lastErr = fmt.Errorf("%w: history size", errInvalid)
			break
		}
		data, err := io.ReadAll(io.LimitReader(file, maxHistoryBytes+1))
		file.Close()
		if err != nil {
			return nil, nil, err
		}
		if lastErr = verifySidecar(path, data); lastErr == nil {
			return st, data, nil
		}
	}
	h.warnOnce(path, id, lastErr)
	return nil, nil, lastErr
}

func verifySidecar(path string, data []byte) error {
	want, err := os.ReadFile(path + historySidecarSuffix)
	if err != nil || len(want) > 128 {
		return fmt.Errorf("%w: history integrity sidecar missing", errInvalid)
	}
	sum := sha256.Sum256(data)
	if strings.TrimSpace(string(want)) != hex.EncodeToString(sum[:]) {
		return fmt.Errorf("%w: history integrity sidecar mismatch", errInvalid)
	}
	return nil
}

// warnOnce logs a refusal once per file version and reason: a new refusal
// after a restore (another identity) or a different reason is logged again.
// The set is bounded; past the cap it is pruned of files that no longer exist
// and, failing that, reset.
func (h *historyState) warnOnce(path string, id fileID, err error) {
	key := warnKey{path, id, err.Error()}
	h.mu.Lock()
	_, seen := h.warned[key]
	if !seen {
		if len(h.warned) >= maxWarned {
			for k := range h.warned {
				if _, statErr := os.Stat(k.path); statErr != nil {
					delete(h.warned, k)
				}
			}
			if len(h.warned) >= maxWarned {
				h.warned = map[warnKey]bool{}
			}
		}
		h.warned[key] = true
	}
	h.mu.Unlock()
	if !seen {
		log.Printf("market-monitor: history file %s refused: %v", path, err)
	}
}

type warnKey struct {
	path   string
	id     fileID
	reason string
}

func dedupe(names []string) []string {
	seen := map[string]bool{}
	out := names[:0:0]
	for _, n := range names {
		if !seen[n] {
			seen[n] = true
			out = append(out, n)
		}
	}
	return out
}
