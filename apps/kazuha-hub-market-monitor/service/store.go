package main

import (
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

// Storage (docs/store-v2.md): one gzip-compressed JSON snapshot per module and
// as-of date under <data>/snapshots/<module>/<YYYY-MM-DD>.json.gz, kept for
// snapshotRetentionDays, and, for margin, panorama and etf, one parquet
// history file per date under <data>/history/<module>/<YYYY-MM-DD>.parquet,
// kept forever (history.go). Re-running a job for the same date replaces that
// date's files; earlier dates are kept.

const (
	snapshotFormat   = "market-monitor.snapshot/1"
	maxSnapshotBytes = 32 << 20
	maxCodeLength    = 16
	// A parsed snapshot takes about 2.1 times its JSON in memory (Panorama:
	// 10.8 MB JSON, 23 MiB parsed), so the cache charges twice the
	// decompressed size, not the gzip file size.
	defaultCacheBudget    = 48 << 20
	cacheChargeFactor     = 2
	snapshotSuffix        = ".json.gz"
	snapshotRetentionDays = 365
	maxFutureDays         = 3
)

var modules = map[string]bool{
	"risk": true, "margin": true, "sentiment": true, "etf": true, "panorama": true,
}

var (
	errNotFound = errors.New("not found")
	errInvalid  = errors.New("invalid snapshot")
)

type snapshot struct {
	Format  string                     `json:"format"`
	Module  string                     `json:"module"`
	AsOf    string                     `json:"as_of"`
	Summary json.RawMessage            `json:"summary"`
	Rows    []map[string]any           `json:"rows"`
	Details map[string]json.RawMessage `json:"details,omitempty"`

	index map[string]int
}

// Store serialises installs and cold loads on ioMu, so a load can never cache
// a file that an install has just replaced, and at most one snapshot is
// being parsed at a time. Cache hits only take mu. History queries have their
// own cache and gate (history.go) and never wait for ioMu.
type Store struct {
	root     string // <data>/snapshots
	histRoot string // <data>/history
	ioMu     sync.Mutex
	hist     *historyState
	now      func() time.Time

	mu          sync.Mutex
	cache       map[string]*snapshot
	sizes       map[string]int
	order       []string // least recently used first
	cachedBytes int
	cacheBudget int
}

func NewStore(dataDir string) *Store {
	return &Store{root: filepath.Join(dataDir, "snapshots"), histRoot: filepath.Join(dataDir, "history"),
		hist: newHistoryState(), now: func() time.Time { return time.Now().UTC() }, cache: map[string]*snapshot{}, sizes: map[string]int{}, cacheBudget: defaultCacheBudget}
}

func (s *Store) cached(key string) (*snapshot, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	snap, ok := s.cache[key]
	if ok {
		s.touchLocked(key)
	}
	return snap, ok
}

func (s *Store) touchLocked(key string) {
	for i, k := range s.order {
		if k == key {
			s.order = append(append(s.order[:i:i], s.order[i+1:]...), key)
			return
		}
	}
}

func (s *Store) dropLocked(key string) {
	if _, ok := s.cache[key]; !ok {
		return
	}
	s.cachedBytes -= s.sizes[key]
	delete(s.cache, key)
	delete(s.sizes, key)
	for i, k := range s.order {
		if k == key {
			s.order = append(s.order[:i:i], s.order[i+1:]...)
			break
		}
	}
}

func (s *Store) putLocked(key string, snap *snapshot, size int) {
	s.dropLocked(key)
	if size > s.cacheBudget {
		return
	}
	for s.cachedBytes+size > s.cacheBudget && len(s.order) > 0 {
		s.dropLocked(s.order[0])
	}
	s.cache[key], s.sizes[key] = snap, size
	s.order = append(s.order, key)
	s.cachedBytes += size
}

func validDate(value string) bool {
	if len(value) != 10 {
		return false
	}
	t, err := time.Parse("2006-01-02", value)
	return err == nil && t.Format("2006-01-02") == value
}

func parseSnapshot(raw []byte) (*snapshot, error) {
	if len(raw) == 0 || len(raw) > maxSnapshotBytes {
		return nil, fmt.Errorf("%w: size", errInvalid)
	}
	var s snapshot
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&s); err != nil {
		return nil, fmt.Errorf("%w: %v", errInvalid, err)
	}
	if _, err := dec.Token(); err != io.EOF {
		return nil, fmt.Errorf("%w: trailing content", errInvalid)
	}
	if s.Format != snapshotFormat || !modules[s.Module] || !validDate(s.AsOf) {
		return nil, fmt.Errorf("%w: identity", errInvalid)
	}
	if len(bytes.TrimSpace(s.Summary)) == 0 || bytes.TrimSpace(s.Summary)[0] != '{' {
		return nil, fmt.Errorf("%w: summary must be an object", errInvalid)
	}
	s.index = make(map[string]int, len(s.Rows))
	for i, row := range s.Rows {
		code, ok := row["code"].(string)
		if !ok || code == "" || len(code) > maxCodeLength {
			return nil, fmt.Errorf("%w: row %d code", errInvalid, i)
		}
		if _, dup := s.index[code]; dup {
			return nil, fmt.Errorf("%w: duplicate code %s", errInvalid, code)
		}
		s.index[code] = i
	}
	for code := range s.Details {
		if _, ok := s.index[code]; !ok {
			return nil, fmt.Errorf("%w: detail without row %s", errInvalid, code)
		}
	}
	return &s, nil
}

// prepared is an output that passed every check and can be committed.
type prepared struct {
	module, asOf string
	raw, history []byte
}

// Prepare validates a module's snapshot document and, for modules that have
// one, its history file, without writing anything. Margin, panorama and etf
// need a history file whose codes equal the snapshot's; the other modules
// must not have one.
func (s *Store) Prepare(module string, raw, history []byte) (*prepared, error) {
	if !modules[module] {
		return nil, fmt.Errorf("%w: module %q", errInvalid, module)
	}
	snap, err := parseSnapshot(raw)
	if err != nil {
		return nil, err
	}
	if snap.Module != module {
		return nil, fmt.Errorf("%w: module %q in %q output", errInvalid, snap.Module, module)
	}
	// A bogus far-future date would make every real snapshot look old to
	// retention, which measures from the module's newest date.
	if asOf, _ := time.Parse("2006-01-02", snap.AsOf); asOf.After(s.now().AddDate(0, 0, maxFutureDays)) {
		return nil, fmt.Errorf("%w: as_of %s is in the future", errInvalid, snap.AsOf)
	}
	if historyModules[module] {
		if history == nil {
			return nil, fmt.Errorf("%w: %s history file missing", errInvalid, module)
		}
		if err := validateHistoryInstall(module, snap, history); err != nil {
			return nil, err
		}
	} else if history != nil {
		return nil, fmt.Errorf("%w: %s has no history", errInvalid, module)
	}
	return &prepared{module: module, asOf: snap.AsOf, raw: raw, history: history}, nil
}

func gzipBytes(raw []byte) ([]byte, error) {
	var buf bytes.Buffer
	zw := gzip.NewWriter(&buf)
	if _, err := zw.Write(raw); err != nil {
		return nil, err
	}
	if err := zw.Close(); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

// Commit writes a prepared output: the history file first, the gzip snapshot
// second. The snapshot is the commit point; a crash in between leaves a
// history file without a snapshot, which the re-run replaces.
func (s *Store) Commit(p *prepared) error {
	packed, err := gzipBytes(p.raw)
	if err != nil {
		return err
	}
	s.ioMu.Lock()
	defer s.ioMu.Unlock()
	if p.history != nil {
		dir := filepath.Join(s.histRoot, p.module)
		if err := os.MkdirAll(dir, 0700); err != nil {
			return err
		}
		// Stage the parquet file first (written and fsynced under its .tmp
		// name), then rename the sidecar, then the parquet file, so on a
		// re-run of a date the old file and the new sidecar disagree for the
		// span of two renames only (see readVerified).
		sum := sha256.Sum256(p.history)
		path := filepath.Join(dir, p.asOf+historySuffix)
		tmp, err := stageFile(path, p.history)
		if err != nil {
			return err
		}
		if err := writeAtomic(path+historySidecarSuffix, []byte(hex.EncodeToString(sum[:])+"\n")); err != nil {
			os.Remove(tmp)
			return err
		}
		if err := renameStaged(tmp, path); err != nil {
			return err
		}
		s.hist.drop(p.module + "/" + p.asOf)
	}
	dir := filepath.Join(s.root, p.module)
	if err := os.MkdirAll(dir, 0700); err != nil {
		return err
	}
	if err := writeAtomic(filepath.Join(dir, p.asOf+snapshotSuffix), packed); err != nil {
		return err
	}
	s.mu.Lock()
	s.dropLocked(p.module + "/" + p.asOf)
	s.mu.Unlock()
	return nil
}

// Install validates and atomically writes one module's outputs and returns
// the as-of date. history is nil for modules without one.
func (s *Store) Install(module string, raw, history []byte) (string, error) {
	p, err := s.Prepare(module, raw, history)
	if err != nil {
		return "", err
	}
	if err := s.Commit(p); err != nil {
		return "", err
	}
	return p.asOf, nil
}

// Retain deletes snapshots more than snapshotRetentionDays older than their
// module's newest snapshot. It never removes a module's newest snapshot, a
// date in protected (the dates installed by the current run, so a backfill is
// not deleted by the run that wrote it) or any history file. It returns what
// it removed; a file it cannot remove is logged and left.
func (s *Store) Retain(protected map[string]map[string]bool) []string {
	s.ioMu.Lock()
	defer s.ioMu.Unlock()
	var removed []string
	for module := range modules {
		dates, err := s.Dates(module)
		if err != nil || len(dates) == 0 {
			continue
		}
		newest, err := time.Parse("2006-01-02", dates[0])
		if err != nil {
			continue
		}
		for _, d := range dates[1:] {
			t, err := time.Parse("2006-01-02", d)
			if err != nil || newest.Sub(t) <= snapshotRetentionDays*24*time.Hour || protected[module][d] {
				continue
			}
			if err := os.Remove(filepath.Join(s.root, module, d+snapshotSuffix)); err != nil && !errors.Is(err, os.ErrNotExist) {
				log.Printf("market-monitor: retention: %s/%s: %v", module, d, err)
				continue
			}
			s.mu.Lock()
			s.dropLocked(module + "/" + d)
			s.mu.Unlock()
			removed = append(removed, module+"/"+d)
		}
	}
	sort.Strings(removed)
	return removed
}

// Dates lists a module's snapshot dates, newest first.
func (s *Store) Dates(module string) ([]string, error) {
	if !modules[module] {
		return nil, errNotFound
	}
	return listDates(filepath.Join(s.root, module), snapshotSuffix)
}

// listDates lists the files in dir named <YYYY-MM-DD><suffix>, newest first.
func listDates(dir, suffix string) ([]string, error) {
	entries, err := os.ReadDir(dir)
	if errors.Is(err, os.ErrNotExist) {
		return []string{}, nil
	}
	if err != nil {
		return nil, err
	}
	dates := []string{}
	for _, e := range entries {
		name := e.Name()
		if e.Type().IsRegular() && strings.HasSuffix(name, suffix) && validDate(strings.TrimSuffix(name, suffix)) {
			dates = append(dates, strings.TrimSuffix(name, suffix))
		}
	}
	sort.Sort(sort.Reverse(sort.StringSlice(dates)))
	return dates, nil
}

// Load returns the snapshot for a date, or the latest one when date is empty.
func (s *Store) Load(module, date string) (*snapshot, error) {
	if !modules[module] {
		return nil, errNotFound
	}
	if date == "" {
		dates, err := s.Dates(module)
		if err != nil {
			return nil, err
		}
		if len(dates) == 0 {
			return nil, errNotFound
		}
		date = dates[0]
	}
	if !validDate(date) {
		return nil, fmt.Errorf("%w: date", errInvalid)
	}
	key := module + "/" + date
	path := filepath.Join(s.root, module, date+snapshotSuffix)
	if snap, ok := s.cached(key); ok {
		// A date removed by hand must stop being served at once.
		if _, err := os.Stat(path); err == nil {
			return snap, nil
		}
		s.mu.Lock()
		s.dropLocked(key)
		s.mu.Unlock()
	}
	s.ioMu.Lock()
	defer s.ioMu.Unlock()
	if snap, ok := s.cached(key); ok {
		return snap, nil
	}
	raw, err := readSnapshotFile(path)
	if err != nil {
		return nil, err
	}
	snap, err := parseSnapshot(raw)
	if err != nil {
		return nil, err
	}
	if snap.Module != module || snap.AsOf != date {
		return nil, fmt.Errorf("%w: stored identity", errInvalid)
	}
	s.mu.Lock()
	s.putLocked(key, snap, cacheChargeFactor*len(raw))
	s.mu.Unlock()
	return snap, nil
}

// readSnapshotFile returns the decompressed document. The reader stops one
// byte past the 32 MiB limit, so the v1 size limit applies to the
// decompressed size and a compression bomb cannot fill memory.
func readSnapshotFile(path string) ([]byte, error) {
	f, err := os.Open(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil, errNotFound
	}
	if err != nil {
		return nil, err
	}
	defer f.Close()
	zr, err := gzip.NewReader(f)
	if err != nil {
		return nil, fmt.Errorf("%w: gzip: %v", errInvalid, err)
	}
	raw, err := io.ReadAll(io.LimitReader(zr, maxSnapshotBytes+1))
	if err != nil {
		return nil, fmt.Errorf("%w: gzip: %v", errInvalid, err)
	}
	return raw, nil
}

// stageFile writes raw to path+".tmp" and fsyncs it; renameStaged makes it the
// real file. writeAtomic is both.
func stageFile(path string, raw []byte) (string, error) {
	tmp := path + ".tmp"
	f, err := os.OpenFile(tmp, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0600)
	if err != nil {
		return "", err
	}
	if _, err := f.Write(raw); err != nil {
		f.Close()
		os.Remove(tmp)
		return "", err
	}
	if err := f.Sync(); err != nil {
		f.Close()
		os.Remove(tmp)
		return "", err
	}
	if err := f.Close(); err != nil {
		os.Remove(tmp)
		return "", err
	}
	return tmp, nil
}

func renameStaged(tmp, path string) error {
	if err := os.Rename(tmp, path); err != nil {
		os.Remove(tmp)
		return err
	}
	if dir, err := os.Open(filepath.Dir(path)); err == nil {
		_ = dir.Sync()
		dir.Close()
	}
	return nil
}

func writeAtomic(path string, raw []byte) error {
	tmp, err := stageFile(path, raw)
	if err != nil {
		return err
	}
	return renameStaged(tmp, path)
}

type rowQuery struct {
	Page, Size int
	Sort       string
	Desc       bool
	Search     string
	Filters    map[string]string
	// Mechanisms are names from mechanismPredicates; a row is kept when it
	// satisfies any of them.
	Mechanisms []string
}

// mechanismPredicates is the closed set of "passive-selling mechanism"
// filters of the margin module, selected by name through the `mechanism`
// query parameter. There are no expressions: a name either exists here or
// the request is refused. A missing value never satisfies a predicate.
var mechanismPredicates = map[string]func(row map[string]any) bool{
	// Two kinds of forced-liquidation cost lines coincide.
	"res2": func(r map[string]any) bool { return numAt(r, "res_cnt", func(x float64) bool { return x >= 2 }) },
	// Share pledge within 15 points of its liquidation line.
	"pledge": func(r map[string]any) bool { return numAt(r, "pld_room", func(x float64) bool { return x < 15 }) },
	// Restricted shares unlock within 60 days.
	"unlock": func(r map[string]any) bool { return numAt(r, "ulk60", func(x float64) bool { return x > 0 }) },
	// Convertible bond trades below its conversion value.
	"cb": func(r map[string]any) bool { return numAt(r, "cb_prem", func(x float64) bool { return x < 0 }) },
	// Block trades at a discount worse than 3%.
	"block": func(r map[string]any) bool { return numAt(r, "blk_disc", func(x float64) bool { return x < -3 }) },
}

func numAt(row map[string]any, field string, test func(float64) bool) bool {
	x, ok := row[field].(float64)
	return ok && !math.IsNaN(x) && test(x)
}

func matchesMechanism(row map[string]any, names []string) bool {
	for _, name := range names {
		if mechanismPredicates[name](row) {
			return true
		}
	}
	return false
}

func matchesFilter(value any, want string) bool {
	text, ok := value.(string)
	if !ok {
		return false
	}
	if text == want {
		return true
	}
	for _, token := range strings.Split(text, "|") {
		if token == want {
			return true
		}
	}
	return false
}

// queryRows filters, sorts and pages rows. Equality filters also match one
// token of a "|"-separated tag list; search matches a code prefix or a name
// substring; numbers sort numerically and missing values always sort last.
func queryRows(rows []map[string]any, q rowQuery) ([]map[string]any, int) {
	out := make([]map[string]any, 0, len(rows))
	for _, row := range rows {
		if q.Search != "" {
			code, _ := row["code"].(string)
			name, _ := row["name"].(string)
			if !strings.HasPrefix(code, q.Search) && !strings.Contains(name, q.Search) {
				continue
			}
		}
		keep := true
		for field, want := range q.Filters {
			if !matchesFilter(row[field], want) {
				keep = false
				break
			}
		}
		if keep && len(q.Mechanisms) > 0 && !matchesMechanism(row, q.Mechanisms) {
			keep = false
		}
		if keep {
			out = append(out, row)
		}
	}
	if q.Sort != "" {
		sort.SliceStable(out, func(i, j int) bool {
			a, b := out[i][q.Sort], out[j][q.Sort]
			if a == nil || b == nil {
				return a != nil && b == nil
			}
			less := compareValues(a, b)
			if q.Desc {
				return less > 0
			}
			return less < 0
		})
	}
	total := len(out)
	start := (q.Page - 1) * q.Size
	if start >= total {
		return []map[string]any{}, total
	}
	end := start + q.Size
	if end > total {
		end = total
	}
	return out[start:end], total
}

func compareValues(a, b any) int {
	if x, ok := a.(float64); ok {
		if y, ok := b.(float64); ok {
			switch {
			case x < y:
				return -1
			case x > y:
				return 1
			}
			return 0
		}
	}
	return strings.Compare(fmt.Sprint(a), fmt.Sprint(b))
}
