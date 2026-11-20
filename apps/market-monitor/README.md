# market-monitor

Daily A-share market monitoring: margin-financing pressure, market sentiment,
broad-ETF fund flows and the Panorama multi-strategy screener, plus the
market-level series intended for a systemic-risk monitor.

**Status: not an installable app yet** — there is no `app.v2.json` and no
`frontend/`, so `scripts/plugin-standard.py` skips this directory and nothing
is published to the catalogue.

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

## `service/` — the managed backend

A Go service on `packages/extensionprotocol`, listening on the platform's Unix
socket:

| Route | Caller | Purpose |
| --- | --- | --- |
| `GET /health/ready` | platform | readiness |
| `POST /v1/handshake` | platform | boot handshake |
| `POST /v1/tasks/run` | platform task, `tasks.schedule` | queue one job: `{"job": "margin"}` |
| `GET /v1/runs` | viewer | job history |
| `GET /v1/{module}/dates` | viewer | snapshot dates, newest first |
| `GET /v1/{module}/summary?date=` | viewer | module summary |
| `GET /v1/{module}/rows?date=&page=&size=&sort=&order=&q=&f.<field>=` | viewer | one page of rows (size ≤ 200) |
| `GET /v1/{module}/rows/{code}?date=` | viewer | one row and its detail |

Viewer routes verify the `X-Portal-Assertion` against the current
registration, boot and request URI, and refuse cookies and authorization
headers. Responses stay under the relay's 1 MiB limit, which is why rows are
paged. A task only queues a job: jobs (`marketdata`, `sentiment`, `panorama`,
`etf`, `margin`) run one at a time inside the container with per-job time
limits, and their snapshot outputs are validated and installed by the service.
Storage layout and rules: [docs/storage.md](docs/storage.md).

The backend container has no network (Portal doc 174). Jobs that fetch data
cannot run on a managed install until the platform provides egress for them;
computing from data already in `/data` works today.

```sh
cd apps/market-monitor/service && go test -race ./...
```

## Next steps

1. Fix the known method defects (unadjusted returns in Panorama, fail-open
   freshness gate, silently stale structure data in the margin scan, ETF
   forward-fill treated as zero flow, hard-coded reporting periods).
2. Add `pipeline/mm_job.py`, the job entry the service calls, which runs each
   job and writes its snapshot document; then the backend image (Go service,
   Python venv and pipeline).
3. Build the dashboards on the shared React SDK (systemic-risk overview and
   margin scan first).
