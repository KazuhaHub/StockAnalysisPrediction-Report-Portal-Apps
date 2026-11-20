# market-monitor store v2: compressed snapshots plus a query history

Status: implemented, 2026-11-20 (see "Implementation notes" at the end). Amends the snapshot storage approved on
2026-11-19 (`storage.md`) before any installation exists, so no data
migration is needed. An earlier draft built on DuckDB and parquet with a
manifest and monthly compaction failed adversarial review (column-name and
type drift, manifest/compaction races, a C/C++ licence surface, frontend
breakage) and is withdrawn.

## Why

1. **Size.** Measured on the real 2026-11-16 data, the five JSON snapshots
   take about 17.8 MB a day (Panorama 10.8 MB, margin 7.0 MB), about 4.4 GB a
   year. `storage.md` estimated 2 MB a day without measuring. The
   installation quota is 3 GiB (Portal docs 182/185; up to 16 GiB by an
   administrator).
2. **Use.** Viewers and the external API (Dify) ask questions across days:
   one stock's margin state over half a year, which stocks have been critical
   five days running, what changed between two dates, how many stocks were in
   each state each day. One multi-megabyte JSON document per module and date
   is the wrong shape for that.

## Design in one paragraph

Snapshots keep their v1 format and are stored gzip-compressed; every
existing route and the frontend are unchanged. Each job also writes, per
module, a small **history file**: one parquet file per as-of date with a
fixed, curated set of columns. The Go service answers four fixed cross-day
queries by reading those files with a pure-Go parquet library. History is
kept forever; full snapshots are kept for 365 days. No database, no cgo, no
manifest, no compaction. Every file stays self-describing, so v1's restore,
deletion and "remove one date by hand" rules still hold.

Measured per day (2026-11-16):

| | margin | panorama | etf | total | per year (250 days) |
|---|---|---|---|---|---|
| snapshot, gzip (v1 content) | 1.45 MB | 2.91 MB | 0.04 MB | 4.4 MB | 1.1 GB |
| history parquet (zstd) | 0.15 MB | 0.39 MB | < 0.01 MB | 0.54 MB | 0.14 GB |

## Layout

```
/data
├── snapshots/<module>/<YYYY-MM-DD>.json.gz    v1 document, gzip; kept 365 days
├── history/<module>/<YYYY-MM-DD>.parquet       curated columns, one row per code; kept forever
├── history/<module>/<YYYY-MM-DD>.parquet.sha256   SHA-256 of that file, written at install
├── runs/ , staging/ , work/                    unchanged
```

Sentiment and risk have no rows, so no history files; their snapshots are
small and also kept 365 days.

## History files

Format `market-monitor.history/1`, written by `mm_job.py` with an explicit
pyarrow schema (never type inference). The service refuses a file whose
column names and types are not exactly the module's schema. A schema change
is a new format version with a reader for both; columns are never retyped
in place.

| Module | Columns (type) |
|---|---|
| margin | `code` string, `name` string, `price` double, `chg` double, `rz` double, `ratio` double, `dratio20` double, `rz_chg5` double, `rz_chg20` double, `buf_call` double, `buf_liq` double, `pnl` double, `score` double, `frag` double, `state` string, `level` string, `tags` string (`\|`-joined, as in v1) |
| panorama | `code` string, `name` string, `sw1` string, `price` double, `mktcap` double, `pe` double, `pb` double, `roe` double, `upside` double, `label` string, `quad` string, `profile` string, `s_value`, `s_growth`, `s_cyclical`, `s_dividend`, `s_momentum`, `s_quality` double |
| etf | `code` string, `name` string, `cat` string, `cum_ytd` double, `cum20` double |

The file's parquet key-value metadata carries `format`, `module` and
`as_of`; the service checks them against the path on install and on read.
History rows are built from the snapshot's rows after `clean()` (so
Panorama's `code` is its `symbol`), which makes the code sets equal by
construction.

Column chunks use ZSTD (UNCOMPRESSED is also read); any other codec is
refused. The footer's claims are bounded before any column is decoded: every
chunk's uncompressed size is at most 32 MiB (128 MiB per file), its compressed
size and page offsets lie inside the file, its value count equals the row
group's, and a row group has at most 20,000 rows.

Casting: a numeric column takes int or float values; anything else (a
string, a bool, NaN, inf) becomes null. A string column takes strings;
anything else becomes null. One odd value never fails a job; the number of
nulled values per column is logged in the run.

## Write path

The job writes, flat in its staging directory as today, `<module>.json`
(and `risk.json`) plus `<module>.history.parquet` for margin, panorama and
etf. A history file is mandatory for those three modules: if it is missing
or invalid (for example pyarrow failed), the run is `output_invalid` and
nothing from it is installed, exactly like an invalid snapshot. The
service, in its existing validate-everything-first loop:

1. Validates the snapshot exactly as v1 does.
2. Validates the history file **in a child process**: the service re-executes
   itself as `market-monitor validate-history <module> <as_of>` with the file on
   stdin. The child caps its address space (`RLIMIT_AS`, 512 MiB above its starting size), opens the
   file with the parquet reader, checks codecs and footer bounds, schema
   equal to the module's, metadata, ≤ 20,000 rows, ≤ 16 MiB, decodes **every**
   column, checks `code` (non-empty, ≤ 16 characters, unique) and prints the
   number and SHA-256 of its sorted codes, which the parent compares with the
   snapshot's row codes. A non-zero exit, a kill (for example out of memory) or
   more than 10 s makes the whole run `output_invalid`. The parent never
   decodes an untrusted file.
   A snapshot or history whose as-of date is more than 3 days after the
   service's current (UTC) date is refused as well, so a bogus far-future date
   cannot drive retention.
3. Installs, per module, the history file first and the gzip snapshot
   second, each with v1's method (write `.tmp`, fsync, rename, fsync the
   directory). The new history file is first written and fsynced under its
   `.tmp` name; then its `<date>.parquet.sha256` sidecar is renamed into
   place; then the parquet file is. On a re-run of a date the old file and
   the new sidecar therefore disagree for the span of two renames. The snapshot is the commit point. A crash between the two
   leaves a history file without its snapshot: harmless, it is listed by
   `/history/dates` and the re-run (the service requeues interrupted runs)
   replaces both. A crash on a **re-run of an existing date** after the sidecar
   was renamed and before the parquet file was (a window of microseconds, but
   real) leaves the old parquet file with the new sidecar: that date answers
   409 `unavailable` until the requeued re-run succeeds, and permanently if the
   re-run keeps failing. An operator recovers by re-running the job for that
   date, or by removing that date's history file and sidecar (the date then
   has no history; its snapshot is unaffected). A re-run of a date replaces both files; each rename is
   atomic and each file is self-contained.
4. Retention, after a successful install: for each module, delete snapshots
   whose as-of date is more than 365 days before that module's newest
   as-of date. Never the module's newest snapshot, never a date installed in
   this run, never history.

`build_risk` in `mm_job.py` checks whether a module's snapshot is installed
by looking for `/data/snapshots/<module>/<as_of>.json`; it changes to
`.json.gz`. `.mm-published` copies are unchanged.

`Dates` lists `*.json.gz`; `Load` opens `<date>.json.gz` and decompresses
through a reader capped at 32 MiB + 1 byte, so the v1 size limit applies to
the decompressed document. No plain `.json` is read.

## Reads

Existing routes keep their contract (`/dates`, `/summary`, `/rows`,
`/rows/<code>`, `/runs`); only the file suffix and decompression change
inside `Dates` and `Load`. `/dates` lists snapshot dates (365 days).

New routes for margin, panorama and etf, all answered from history files:

| Route | Answers | Rules and bounds |
|---|---|---|
| `GET /v1/<m>/history/dates` | every history date, newest first | — |
| `GET /v1/<m>/history?code=&fields=&from=&to=` | one code's values over time | `fields` ⊆ the module's columns, ≤ 8; ≤ 250 dates per request (page further back with `to`); dates without the code are omitted |
| `GET /v1/<m>/compare?from=&to=&fields=&changed=&page=&size=` | each code's values on two dates | full outer join on `code` (a side may be null), ordered by code; `fields` ≤ 8; `changed=<field>` keeps codes whose value differs (null ≠ value; a code present on one side only is changed), allowed for string fields except `tags`; numeric fields return both values and the difference; size ≤ 100 |
| `GET /v1/<m>/streak?field=&op=&value=&days=&date=&page=&size=` | codes meeting a condition on each of the last N history dates up to `date` (default: the newest) | `op` `eq` for string fields except `tags`, `eq`/`gte`/`lte` for numeric; null fails the condition; `days` 1–60; `date` must be a history date; ordered by code; the response lists the N dates used, so a gap (a failed day) is visible; size ≤ 200 |
| `GET /v1/<m>/counts?field=&from=&to=` | per date, rows per value of a categorical field; nulls reported separately as `nulls` | field allowlist: margin `state`, `level`; panorama `label`, `quad`, `profile`, `sw1`; etf `cat`; ≤ 500 dates |

Rows returned by `compare` and `streak` carry `code` and `name` (from the
history file), so a caller needs no second lookup. The routes answer 404
for `risk` and `sentiment`.

Dates are as-of dates; the service has no trading calendar, so "the last N
days" means the last N history files, and the dates are always returned.

Limits (measured: parquet-go, one core; 1,500 Panorama files × 8 fields
took 3.2–4.8 s on a fast desktop core, 500 files × 1 field 0.18 s):

- Responses stay under the relay's 1 MiB (page sizes and caps above;
  measured worst cases about 330 KB).
- One history query runs at a time; another arriving meanwhile gets 429
  `busy`. On one CPU, two concurrent scans would only both time out.
- Each query checks a 4 s deadline between files and stops with 409
  `query_timeout` (the server's write timeout is 5 s, after which the relay
  would see a broken connection instead of a status).
- Each query reads only the columns it needs.
- Integrity: on every cold read the file's SHA-256 is compared with its
  sidecar **before** it is parsed; a missing or mismatched sidecar makes that
  date 409 `unavailable` (logged once) and nothing is decoded. The hash runs
  once per file version, because the cache below is keyed by file identity.
- History cache: parsed columns up to 64 MiB, keyed by file identity
  (device, inode, size, modification time) and checked with `stat` on every
  use, so a hand-removed date, a restore or a doc 185 import is noticed
  without an install. A query touching more than 60 files reads without
  filling the cache, so one long scan does not evict the working set.
- Snapshot cache: v1's 48 MiB budget is charged at twice the decompressed
  size (a parsed document measures about 2.1× its JSON: Panorama 10.8 MB
  JSON → 23 MiB parsed), not at the gzip size.
- Memory: about 112 MiB for both caches plus one request's transient parse
  (~35 MiB), next to the largest job (Panorama, peaks about 1.2 GB) inside
  2048 MiB.

## Seeding

The seed (Portal doc 185 administrator import) carries `work/` plus the
snapshots and history files for the seed's latest as-of date, built by the
same converters, so the dashboards show data from the first day and history
grows from there. No backfill of older history. Each history file in the seed must carry its
`<date>.parquet.sha256` sidecar (the lowercase hex SHA-256 of the parquet file
and a newline); a seeded date without it, or with a stale one, answers 409
`unavailable`. Produce the pair with the same writer an install uses (install
the converters' output through the service) or by hand:
`sha256sum <date>.parquet | cut -d' ' -f1 > <date>.parquet.sha256`.

## Capacity (3 GiB quota)

| Part | Size |
|---|---|
| `work/` after seeding | ≈ 0.75 GB, + ~0.3 GB/year (pipeline README: daily increments ≈ 300 MB a year) |
| MarketData pre-write copies if hard links are refused | ≈ 0.15 GB |
| snapshots (365 days × 4.4 MB) | ≈ 1.1 GB, flat after the first year |
| history | ≈ 0.14 GB/year |
| runs, staging | < 0.1 GB |

About 2.5 GB after one year, growing about 0.45 GB a year after that. The
3 GiB quota is reached in about two years, so the installation should get
**6 GiB** (doc 185 allows up to 16 GiB): about eight years. The service logs a
warning when `/data` use passes 80 % of the quota.

## Build and licences

- Parquet in Go: `github.com/parquet-go/parquet-go` (Apache-2.0, no cgo;
  its dependencies are BSD/MIT/Apache). These are the service's first
  third-party Go modules: pinned in `go.sum`, downloaded with
  `go mod download` in the image build and in CI. `CGO_ENABLED=0` stays.
- The licence gate today scans only the status and scheduled-digest Go
  modules; the market-monitor service is added to it.

## Versioning

`/health/ready` reports `data_format: "2"`. Snapshot documents keep
`market-monitor.snapshot/1`; history files carry
`market-monitor.history/1` in their parquet key-value metadata. Restore and
deletion are unchanged from `storage.md`: every file is self-describing;
removing one date by hand removes that date's snapshot, history file and
history sidecar. A history file placed by hand (a restore, a doc 185 import)
must come with its sidecar, or that date is unavailable.

## Frontend and development

The frontend is unchanged in this step. The dev preview
(`MM_SNAPSHOT_DIR`) and `TestSnapshotsFromARealRun` read plain `.json`:
snapshots copied from `/data` must be gunzipped first (README). The new routes serve the external API first; a
history view in the dashboards is a later change.

## Tests

- Converters: history schema exactly as specified for the real 2026-11-16
  data; casting of odd values to null with a count; same codes as the
  snapshot.
- Install: v1 checks still apply; history schema, size, row and code checks;
  re-run replaces; gzip round trip; retention removes only snapshots older
  than 365 days.
- Crafted files: single-byte corruptions of real history files (an LZ4 codec
  whose decoder grows past 1 GiB, a page header that allocates 800 MB) are
  refused on install (codec allowlist, footer bounds, child process) and on
  read (sidecar) without the service's heap growing; the codec allowlist, the
  child's every-column decode and its failure modes (exit, kill, timeout), the
  sidecar and the future-date rule have their own tests.
- Caching: a file replaced or removed under the cache is not served; an
  install racing a query does not leave stale columns.
- Retention: measured from the newest as-of; a backfilled old date and a
  module's newest snapshot are never removed.
- Routes: each new route on a multi-day fixture (codes appearing and
  disappearing, nulls, a missing day); bounds and refusals; field names
  outside the schema; 1 MiB; concurrency limit and timeout.
- `build_risk` with `.json.gz`.
- Image: CI writes history files with the image's pyarrow as the container
  user, runs the shipped binary's `validate-history` on them in the restricted
  container, and has the Go reader install them. A viewer query through the
  socket needs a signed client and is checked by hand, not in CI. The pipeline
  CI job installs the image's pyarrow version and fails if a history test is
  skipped.

## Implementation notes

Choices the sections above leave open. The code is `service/history.go`
(files, cache, validation), `service/history_api.go` (routes) and
`service/store.go` (install, retention).

- **Statuses.** A malformed parameter, an unknown or repeated key, or a field
  outside the module's schema is 400 `bad_request`. A date that is not a
  history date (`compare` from/to, `streak` date) is 404 `no_data`, as for
  `/rows?date=`. 429 `busy`, 409 `query_timeout` and 404 for `risk` and
  `sentiment` are as specified. A history file that fails validation on read
  (wrong schema, wrong metadata for its path, corrupt) is 409 `unavailable`;
  it is never skipped silently. `/history/dates` is not a history query and is
  not gated.
- **Order.** `history` and `counts` return their dates oldest first (a series
  as plotted). When a window is cut at its cap, the newest dates are kept,
  `truncated` is true and `next_to` is the newest date not returned: pass it as
  `to` to page back. `history/dates` is newest first.
- **Parameters.** `history`: `code` and `fields` required. `compare`: `from`
  and `to` required, `fields` optional (an empty `fields=` is refused),
  `changed` must be a string column other than `tags`, page 1.., size 1-100
  (default 50). `streak`: `field`, `op`, `value`, `days` required; a numeric
  `value` is finite; a string `value` is at most 64 characters; size 1-200
  (default 50). `counts`: `field` from the allowlist.
- **Shapes.** `compare` items are `{code, name, from, to, diff}`: `from` or
  `to` is null when the code is absent on that side, `diff` is always an
  object holding the numeric fields only (empty when none were requested; a
  field is null if either side is null). `name` is the `to` side's, else the
  `from` side's when the code is absent from `to`; a null name is null.
  `changed` keeps a code that is on one side only (absent is not a null
  value). `streak` returns `dates` (the N
  dates used, newest first), `complete` (false when the history has fewer than
  `days` dates, in which case nobody qualifies) and items `{code, name}`.
  `counts` items are `{date, counts: {value: n}, nulls: n}`, so a value that
  is literally the text "null" cannot collide with the nulls.
- **Cache.** A query reads the whole set of columns it needs from the file it
  opened, never mixing cached and fresh columns; the identity (device, inode,
  size, mtime) comes from the open handle. A query that reads more than 60
  files neither reads from nor fills the cache.
- **Untrusted history files.** A zstd file of 16 MiB does not bound its own
  expansion, and a flipped byte can send the parquet library's decoders (a
  page header, an LZ4 codec) into allocations Go cannot recover from. Hence:
  the codec allowlist and footer bounds above; install validation in a child
  with `RLIMIT_AS` (512 MiB of headroom over the child's starting address space,
  enforced on Linux only; an absolute 512 MiB cannot work because a Go
  process starts with about 1.3 GB of address space reserved, measured, and
  failed at random up to 1 GiB, while a real file adds about 1 MB; development hosts run it
  without a cap); and the SHA-256 sidecar, which makes the read path decode
  only bytes the installer validated. The sidecar is written before the
  parquet file is renamed, so a read racing a re-run of the same date may see
  a new sidecar with the old file; the reader retries once, then reports
  `unavailable`.
- **Residual risk.** Whoever can write into `/data/history` can write a file
  and its matching sidecar and so bypass the install-time child; the read path
  then relies on the codec allowlist and footer bounds alone, and a crafted
  page header in such a file could still exhaust the service's memory.
  `/data` is writable only by the service and by an administrator's import
  (doc 185), who is trusted with the data; the service does not defend
  against that import.
- **Run error codes.** A history file that the validator judges bad (a
  verdict: bad schema, codec, bounds, codes, a decode error, running out of
  its memory cap, the 10 s limit) is `output_invalid`. A failure of the
  validation machinery (the service cannot locate or start its child, cannot
  read `/proc/self/status` to set the cap, or the child is killed by a
  signal) is `validator_unavailable`, with a log line saying the output was
  not judged; the job is not blamed and a later run retries. The child's exit
  statuses are 1 bad file, 2 Go runtime fatal (memory), 3 environment, 4
  usage.
- **Refusal log.** A refused history file is logged once per file version
  (identity) and reason; the set is bounded (256 entries).
- **Time.** The as-of future check uses the service's UTC clock plus 3 days.
- **Quota warning.** The service has no quota API; it uses `statfs` on `/data`,
  which on an XFS project-quota directory reports the quota as the filesystem
  size (so "80 % of the quota"), and on a directory without a quota the size of
  the filesystem. It checks at start and after every run.
