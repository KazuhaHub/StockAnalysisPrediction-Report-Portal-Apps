# market-monitor

Daily A-share market monitoring: margin-financing pressure, market sentiment,
broad-ETF fund flows and the Panorama multi-strategy screener, plus the
market-level series intended for a systemic-risk monitor.

**Status: source import only. This directory is not an installable app yet** —
it has no `app.v2.json` and no `frontend/`, so `scripts/plugin-standard.py`
skips it and nothing is published to the catalogue.

## `pipeline/` — imported upstream code

`pipeline/` is the handed-over daily-task bundle, imported as-is so later
changes can be reviewed against the original:

- Source: `daily-tasks-20261117.tar.gz`, sha256
  `5326ab2659db605035f6df83de3021d1eb5c2420f5d8fb0f548032e4a43de56e`.
- Kept: Python and shell sources, systemd/cron/nginx examples, requirements,
  Markdown docs, and the hand-written dashboard sources used as UI reference.
- Left out: market data and generated outputs (parquet, JSON, CSV, logs, built
  HTML, `payload.js`/`data.js`), vendored minified libraries, interpreter caches
  and runtime state files. The 2014-onward bar store (about 510 MB) is kept
  outside git.
- Changed on import: `workspace/analysis/panel/source_legacy.py` reads its
  share code and password from `LEGACY_SHARE_CODE` / `LEGACY_SHARE_PASSWORD`
  instead of literals, and two report notes have the share code redacted.

Comments and docs inside `pipeline/` are the original Chinese text; they are
third-party input, not developer text written for this repository.

## Next steps

1. Fix the known method defects (unadjusted returns in Panorama, fail-open
   freshness gate, silently stale structure data in the margin scan, ETF
   forward-fill treated as zero flow, hard-coded reporting periods).
2. Wrap the pipeline in a v2 backend: a small Go service built on
   `packages/extensionprotocol` handles the platform protocol, schedules the
   jobs as background tasks and serves read endpoints; the Python jobs keep
   running unchanged behind it.
3. Build the dashboards on the shared React SDK (systemic-risk overview and
   margin scan first).
