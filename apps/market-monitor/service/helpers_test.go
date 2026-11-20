package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"os"
	"reflect"
	"strconv"
	"testing"

	"github.com/parquet-go/parquet-go"
	"github.com/parquet-go/parquet-go/compress"
	"github.com/parquet-go/parquet-go/compress/zstd"
)

// histSpec describes a history file to build. The zero value (after
// defaults) is a valid market-monitor.history/1 file; the fields let a test
// break exactly one rule.
type histSpec struct {
	module, asOf string
	format       string
	metaModule   string
	metaAsOf     string
	dropMeta     string
	codec        compress.Codec
	columns      []histCol // schema override (names and types)
	required     bool      // write required instead of optional columns
	rows         []map[string]any
	repeat       int // write every row this many times (row-count tests)
}

// historyFile builds a history parquet file the way mm_job.py does: an
// explicit schema in the module's column order, optional columns, zstd and
// key-value metadata.
func historyFile(t testing.TB, spec histSpec) []byte {
	t.Helper()
	if spec.format == "" {
		spec.format = historyFormat
	}
	if spec.metaModule == "" {
		spec.metaModule = spec.module
	}
	if spec.metaAsOf == "" {
		spec.metaAsOf = spec.asOf
	}
	cols := spec.columns
	if cols == nil {
		cols = historySchemas[spec.module]
	}
	fields := make([]reflect.StructField, len(cols))
	for i, c := range cols {
		typ := reflect.TypeOf((*float64)(nil))
		if c.str {
			typ = reflect.TypeOf((*string)(nil))
		}
		tag := `parquet:"` + c.name + `,optional"`
		if spec.required {
			typ = typ.Elem()
			tag = `parquet:"` + c.name + `"`
		}
		fields[i] = reflect.StructField{Name: "F" + strconv.Itoa(i), Type: typ, Tag: reflect.StructTag(tag)}
	}
	structType := reflect.StructOf(fields)
	var buf bytes.Buffer
	var codec compress.Codec = &zstd.Codec{}
	if spec.codec != nil {
		codec = spec.codec
	}
	opts := []parquet.WriterOption{parquet.SchemaOf(reflect.New(structType).Elem().Interface()),
		parquet.Compression(codec)}
	meta := map[string]string{"format": spec.format, "module": spec.metaModule, "as_of": spec.metaAsOf}
	delete(meta, spec.dropMeta)
	for k, v := range meta {
		opts = append(opts, parquet.KeyValueMetadata(k, v))
	}
	w := parquet.NewWriter(&buf, opts...)
	repeat := max(spec.repeat, 1)
	for r := 0; r < repeat; r++ {
		for _, row := range spec.rows {
			v := reflect.New(structType).Elem()
			for i, c := range cols {
				raw := row[c.name]
				if r > 0 && c.name == "code" {
					raw = row["code"].(string) + "-" + strconv.Itoa(r)
				}
				field := v.Field(i)
				switch x := raw.(type) {
				case string:
					if c.str {
						set(field, reflect.ValueOf(x))
					}
				case float64:
					if !c.str {
						set(field, reflect.ValueOf(x))
					}
				case int:
					if !c.str {
						set(field, reflect.ValueOf(float64(x)))
					}
				}
			}
			if err := w.Write(v.Interface()); err != nil {
				t.Fatal(err)
			}
		}
	}
	if err := w.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

// set assigns value to a pointer (optional) or plain (required) field.
func set(field, value reflect.Value) {
	if field.Kind() == reflect.Pointer {
		p := reflect.New(value.Type())
		p.Elem().Set(value)
		field.Set(p)
		return
	}
	field.Set(value)
}

// defaultRows are the three rows testSnapshot uses for margin.
func defaultRows() []map[string]any {
	return []map[string]any{
		{"code": "600000", "name": "A", "frag": 90.0, "state": "临界", "tags": "价跌加杠杆|占比畸高"},
		{"code": "000001", "name": "B", "frag": 30.0, "state": "安全", "tags": ""},
		{"code": "300001", "name": "C", "frag": nil, "state": "潜伏", "tags": "占比畸高"},
	}
}

// testHistory builds the history file for the rows of testSnapshot(module,
// asOf, rows...), so the two always agree on codes.
func testHistory(t testing.TB, module, asOf string, rows ...map[string]any) []byte {
	if rows == nil {
		rows = defaultRows()
	}
	return historyFile(t, histSpec{module: module, asOf: asOf, rows: rows})
}

// installTest installs a snapshot and, for modules with history, its history.
func installTest(t testing.TB, s *Store, module, asOf string, rows ...map[string]any) {
	t.Helper()
	var history []byte
	if historyModules[module] {
		history = testHistory(t, module, asOf, rows...)
	}
	if _, err := s.Install(module, testSnapshot(module, asOf, rows...), history); err != nil {
		t.Fatalf("install %s %s: %v", module, asOf, err)
	}
}

// TestMain lets the test binary play the validate-history child that the
// service starts by re-executing itself.
func TestMain(m *testing.M) {
	if len(os.Args) > 1 && os.Args[1] == validateHistoryArg {
		os.Exit(runValidateHistory(os.Args[2:], os.Stdin, os.Stdout, os.Stderr))
	}
	os.Exit(m.Run())
}

// putHistoryFile writes a history file and its integrity sidecar the way an
// install does (sidecar first), for tests that place files by hand.
func putHistoryFile(t testing.TB, path string, data []byte) {
	t.Helper()
	sum := sha256.Sum256(data)
	if err := writeAtomic(path+historySidecarSuffix, []byte(hex.EncodeToString(sum[:])+"\n")); err != nil {
		t.Fatal(err)
	}
	if err := writeAtomic(path, data); err != nil {
		t.Fatal(err)
	}
}

func historyFileWithCodec(t testing.TB, spec histSpec, codec compress.Codec) []byte {
	spec.codec = codec
	return historyFile(t, spec)
}
