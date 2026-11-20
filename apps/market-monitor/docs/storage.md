# market-monitor storage

Approved by the owner on 2026-11-19: one snapshot file per module per as-of
date, history kept; viewer reads are split by module into summary, paged rows
and single-row detail.

Everything lives in the installation's `/data` mount. The Go service is the
only writer of `snapshots/` and `runs/`; Python jobs write only to their own
staging directory and to the market-data store.

```
/data
├── snapshots/<module>/<YYYY-MM-DD>.json   one document per module and as-of date
├── runs/index.json                        job history, newest first, at most 200 runs
├── runs/<run-id>.log                      job output, first 256 KiB per attempt
├── staging/<run-id>/                      a running job's output, removed when it ends
└── marketdata/                            the bar store (bars/YYYY.parquet, meta.json)
```

Modules: `risk`, `margin`, `sentiment`, `etf`, `panorama`.

## Snapshot document

```json
{
  "format": "market-monitor.snapshot/1",
  "module": "margin",
  "as_of": "2026-11-18",
  "summary": { "...": "module-wide figures and series, a JSON object" },
  "rows": [ { "code": "600000", "name": "...", "...": "one object per stock or fund" } ],
  "details": { "600000": { "...": "optional per-row extras, such as a 60-day series" } }
}
```

Rules enforced on install (`store.go`):

- `format` is exactly `market-monitor.snapshot/1`; unknown top-level fields are refused.
- `module` is one of the five modules and equals the output file name the job wrote.
- `as_of` is a real calendar date in `YYYY-MM-DD`; it names the file.
- `summary` is a JSON object; `rows` is an array of objects, each with a unique
  non-empty `code` of at most 16 characters; every `details` key names a row.
- A document is at most 32 MiB.

`as_of` is the data's base date, not the time the job ran. Re-running a job for
the same date replaces that date's file; earlier dates are never touched.

Writes go to `<file>.tmp`, are fsynced, renamed over the target and the
directory is fsynced, so a crash leaves either the old or the new document.
A job's outputs are all validated before any is installed; installing is then
one module at a time, and a run that fails part-way lists the modules it did
install.

## Runs

`runs/index.json` is `{"format": "market-monitor.runs/1", "runs": [...]}`.
A run is `queued`, `running`, `succeeded`, `failed` or `interrupted`; a failed
run's `error` is a short code (`exit_status`, `timeout`, `output_invalid`, …)
and the reason is in its log. Viewers see runs without the platform task ID.

Jobs are idempotent per as-of date, so a run that was queued or running when
the service stopped is queued again at the next start. Only a run that was
actually running uses up an attempt; after 3 interrupted attempts it is marked
`interrupted`. A platform task ID maps to exactly one run: a redelivery
with the same job and occurrence returns that run, and a different job or
occurrence under the same task ID is refused. Duplicate detection covers the
200 runs kept in the index.

## Restore and deletion

- **Backup/restore:** the platform checkpoints and restores the whole `/data`
  mount. Snapshots are self-describing and need no migration within format
  `/1`; runs restored as `queued` or `running` are queued again on start,
  within the same attempt limit.
- **Data format changes:** a new snapshot format gets a new `format` string
  and a reader for both; an existing format is never rewritten in place.
- **Deletion:** uninstalling with data deletion removes the mount; there is no
  partial delete. Removing one date by hand is safe: readers only list files
  that parse as dates.
- **Retention:** snapshots are kept indefinitely; at roughly 2 MB a day for all
  modules that is under 1 GB a year. A retention rule, if needed, is a later
  decision for the owner.
