# market-monitor

Daily A-share market monitoring: margin-financing pressure, market sentiment,
broad-ETF fund flows and the Panorama multi-strategy screener, plus the
market-level series intended for a systemic-risk monitor.

**Status: development app.** `app.v2.json` declares five document routes
(overview, margin, sentiment, ETF, Panorama) and the backend image; the image
digest is a placeholder until a release is built, so nothing is published to
the catalogue yet.

## `frontend/` — dashboards

React + Ant Design on `@portal-app/sdk/root-v2`, charts with ECharts (only
the chart types used are bundled). Every page reads the backend through
`useAppBackend`: summary for the dashboard, server-paged rows for the margin,
ETF and Panorama tables, and `/rows/<code>` for a row's drawer. Colours come
from the host theme tokens, so light and dark both work; up is red, down
green.

Local preview with real snapshots (development only, never packaged):

```sh
cd apps/market-monitor/frontend
MM_SNAPSHOT_DIR=/path/to/snapshots npm run dev   # <dir>/<module>/<date>.json
```

Open `http://127.0.0.1:5173/`. `dev/host.html` is a stand-in host using the
SDK's `createBridgeHost` in a sandboxed frame; `?path=/margin&dark=1&locale=en-US`
picks the start state. `dev/mock-backend.mjs` answers the `/v1` routes like the
Go service (same paging, sort and filter rules) and keeps loaded files in
memory, so restart it after changing the fixtures.

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

**Schedule.** The platform cannot yet originate tasks for a managed backend
(its `tasks/background` route is not reachable from a networkless container),
so the service keeps the pipeline's timetable itself, in Beijing time: marketdata Mon–Fri 21:00 with a 23:30 fallback; sentiment
00:40, panorama 00:50 and ETF 08:00 Tue–Sat; margin Mon–Fri 09:00 with a 09:50
fallback. A fallback runs only when no run of the job queued earlier that day
(scheduled or manual) succeeded or is pending. Each occurrence is one run with task ID
`schedule/<job>/<YYYY-MM-DDTHH:MM>`, so ticks and restarts never repeat it; on
start, each slot's latest occurrence in the past 20 hours runs once if it never
did. `POST /v1/tasks/run` stays available to start a job by hand.

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

## `pipeline/mm_job.py` — the job entry

The service runs `mm_job.py <job>`. It copies the pipeline code into
`/data/work` (the pipeline's install prefix and `HOME`; data there is kept),
clears locks a killed run may have left, starts the pipeline's data server
(`stock_server`, loopback port 8091) for the jobs that need it, runs the
pipeline's own script unchanged, and converts the output **this run wrote**
into snapshot documents. Output older than the run is refused, so a pipeline
that skips and exits 0 never republishes old data.

| Job | Pipeline script | Data server | Snapshots |
| --- | --- | --- | --- |
| `marketdata` | `MarketData/update.sh` | yes | none (updates the bar store) |
| `sentiment` | `workspace/analysis/sentiment_daily.py` | no | `sentiment`, `risk` |
| `panorama` | `workspace/panorama/daily_update.sh` | yes | `panorama` |
| `etf` | `workspace/analysis/panel/refresh.sh` | no | `etf`, `risk` |
| `margin` | `margin_scan/update.sh` | no | `margin`, `risk` |

`risk` combines the readings of the margin, sentiment and ETF snapshots: the
one being published and the others only once the service has installed them,
so it never cites a failed run's output or a refused snapshot. Each part
keeps its own `as_of` and the document is dated by the newest. The outer
`bin/run_*.sh` wrappers are not used: they wait on an online trading
calendar and publish HTML to nginx.

Exit codes: the pipeline's own non-zero code, passed through; 2 usage; 91
output missing; 92 output not written by this run; 93 environment (the
`/opt/daily-tasks` link, or the data server's port is taken or it did not
start). The data server logs to `/data/work/stock_server/server.log`.

Deployment constraint: one `/data` has one runner. Clearing stale locks
assumes no other container or hand-run pipeline script writes the same work
directory.

Two pipeline fixes ride along, both so stale data cannot pass as fresh:
`MarketData/update.sh` now returns the update/check exit code (it always
exited 0), and Panorama's freshness check refuses to publish when the
trading calendar is unreachable (it used to pass). A deliberate backfill
sets `PANORAMA_ASOF`, which skips that check.

Checked against real data (the 2026-11-17 bundle): `sentiment` runs end to
end offline; `panorama` refuses without the calendar and completes with
`PANORAMA_ASOF`; the `margin` and `etf` conversions were checked on their
last outputs; every snapshot installs in the Go store and the first page,
the summary and every row detail stay under 1 MiB. To repeat the store check:
`MM_SNAPSHOT_DIR=<dir of snapshots> go test -run TestSnapshotsFromARealRun ./...`.

Still to verify once the platform provides egress: with the data server up,
Panorama's freshness check compares the last bar with the calendar's
previous trading day; an evening run after that day's bars are written must
pass.

Known limit: when every ETF feed fails, `refresh.sh` recomputes from its
stored data and exits 0, so the ETF snapshot can carry an older `as_of`;
its `summary.data_health` shows each source's last date.

## Backend image

```sh
docker build --platform linux/amd64 -f apps/market-monitor/service/Dockerfile -t market-monitor .
```

One image holds the Go service (`/app/market-monitor`, the entrypoint), the
pipeline (`/app/pipeline`) and its virtual environment (`/app/venv`, installed
from `pipeline/requirements.lock`). `/opt/daily-tasks` links to `/data/work`.
It runs as the platform runs it: user 65532, read-only root, no network,
16 MiB `/tmp`, data at `/data`, `TZ=Asia/Shanghai` (the scripts use local
dates for trading days). About 240 MiB compressed with `gzip -1` (the package
limit is 384 MiB). linux/amd64 only: py-mini-racer has no arm64 wheel.

The job entry sets `MM_NO_HTML=1`, and the margin, ETF and Panorama scripts
then skip their own HTML pages (the app has its own frontend, and the pages
need vendored echarts/mermaid that are not in this repository). Without the
variable the scripts behave exactly as before.

`requirements.lock` pins every package. akshare is pinned to 1.18.94, the
version that runs on the production host: from 1.20.45 on, akshare renamed
functions this code calls (`tool_trade_date_hist_sina` among them), and the
margin job failed on them. To change a version, re-resolve in a clean
`python:3.11-slim` container and re-freeze, then rerun the jobs.

Checked end to end in that container with a Portal-side test client
(handshake, task trigger, signed viewer reads): `sentiment` and `panorama`
(with `PANORAMA_ASOF`) install their snapshots, viewer reads return them,
unsigned reads get 403, and `margin` fails only where it first needs the
network.

## Next steps

0. Seed a new installation: a fresh `/data` has no bar store (2014 onwards,
   about 510 MB) or Panorama base data, so every job fails until a one-time
   import loads them.

1. Fix the known method defects (unadjusted returns in Panorama, fail-open
   freshness gate, silently stale structure data in the margin scan, ETF
   forward-fill treated as zero flow, hard-coded reporting periods).
2. Wire egress through the platform's reviewed forward proxy (Portal doc
   184) and switch the few `http://` sources to `https://`.
3. Panorama: the industry breakdown, market medians and valuation shifts
   come from the export step's page data (`site/data.js`), used only when
   that run wrote it for the same date; see `convert_panorama`.
