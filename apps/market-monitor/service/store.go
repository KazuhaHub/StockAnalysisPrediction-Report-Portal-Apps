package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

// Snapshots are the app's only business storage: one immutable JSON document
// per module and as-of date under <data>/snapshots/<module>/<YYYY-MM-DD>.json.
// Re-running a job for the same date replaces that date's document; earlier
// dates are kept, which is what gives the dashboards their history.

const (
	snapshotFormat   = "market-monitor.snapshot/1"
	maxSnapshotBytes = 32 << 20
	maxCodeLength    = 16
	// Parsed snapshots take several times their file size in memory; the
	// budget counts file bytes and keeps the cache well inside the container.
	defaultCacheBudget = 48 << 20
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
// being parsed at a time. Cache hits only take mu.
type Store struct {
	root string
	ioMu sync.Mutex

	mu          sync.Mutex
	cache       map[string]*snapshot
	sizes       map[string]int
	order       []string // least recently used first
	cachedBytes int
	cacheBudget int
}

func NewStore(dataDir string) *Store {
	return &Store{root: filepath.Join(dataDir, "snapshots"), cache: map[string]*snapshot{},
		sizes: map[string]int{}, cacheBudget: defaultCacheBudget}
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

// Install validates a snapshot for the named module and atomically writes it.
func (s *Store) Install(module string, raw []byte) (string, error) {
	if !modules[module] {
		return "", fmt.Errorf("%w: module %q", errInvalid, module)
	}
	snap, err := parseSnapshot(raw)
	if err != nil {
		return "", err
	}
	if snap.Module != module {
		return "", fmt.Errorf("%w: module %q in %q output", errInvalid, snap.Module, module)
	}
	dir := filepath.Join(s.root, module)
	if err := os.MkdirAll(dir, 0700); err != nil {
		return "", err
	}
	s.ioMu.Lock()
	defer s.ioMu.Unlock()
	if err := writeAtomic(filepath.Join(dir, snap.AsOf+".json"), raw); err != nil {
		return "", err
	}
	s.mu.Lock()
	s.dropLocked(module + "/" + snap.AsOf)
	s.mu.Unlock()
	return snap.AsOf, nil
}

// Dates lists a module's snapshot dates, newest first.
func (s *Store) Dates(module string) ([]string, error) {
	if !modules[module] {
		return nil, errNotFound
	}
	entries, err := os.ReadDir(filepath.Join(s.root, module))
	if errors.Is(err, os.ErrNotExist) {
		return []string{}, nil
	}
	if err != nil {
		return nil, err
	}
	dates := []string{}
	for _, e := range entries {
		name := e.Name()
		if e.Type().IsRegular() && strings.HasSuffix(name, ".json") && validDate(strings.TrimSuffix(name, ".json")) {
			dates = append(dates, strings.TrimSuffix(name, ".json"))
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
	path := filepath.Join(s.root, module, date+".json")
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
	raw, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil, errNotFound
	}
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
	s.putLocked(key, snap, len(raw))
	s.mu.Unlock()
	return snap, nil
}

func writeAtomic(path string, raw []byte) error {
	tmp := path + ".tmp"
	f, err := os.OpenFile(tmp, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	if _, err := f.Write(raw); err != nil {
		f.Close()
		os.Remove(tmp)
		return err
	}
	if err := f.Sync(); err != nil {
		f.Close()
		os.Remove(tmp)
		return err
	}
	if err := f.Close(); err != nil {
		os.Remove(tmp)
		return err
	}
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

type rowQuery struct {
	Page, Size int
	Sort       string
	Desc       bool
	Search     string
	Filters    map[string]string
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
