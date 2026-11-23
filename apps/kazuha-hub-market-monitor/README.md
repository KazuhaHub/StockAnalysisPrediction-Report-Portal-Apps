# kazuha-hub-market-monitor

Daily A-share market monitoring: margin-financing pressure, market sentiment,
broad-ETF fund flows and the Panorama multi-strategy screener, plus the
market-level series intended for a systemic-risk monitor.

**Status: beta.** `app.v2.json` declares five document routes
(overview, margin, sentiment, ETF, Panorama), one admin route (`/admin`) and
the backend image; the image
digest is a placeholder in the source, replaced when the
`release-market-monitor` workflow builds, signs and publishes a package
(docs/publisher-v2.md, "Release signing in CI").

## `frontend/` — dashboards

React + Ant Design on `@portal-app/sdk/root-v2`, charts with ECharts (only
the chart types used are bundled). Every page reads the backend through
`useAppBackend`: summary for the dashboard, server-paged rows for the margin,
ETF and Panorama tables, and `/rows/<code>` for a row's drawer. Colours come
from the host theme tokens, so light and dark both work; up is red, down
green.

Local preview with real snapshots (development only, never packaged):

```sh
cd apps/kazuha-hub-market-monitor/frontend
MM_SNAPSHOT_DIR=/path/to/snapshots npm run dev   # <dir>/<module>/<date>.json
```

The preview reads plain JSON. Snapshots in `/data/snapshots/<module>/` are
gzip files (`<date>.json.gz`, docs/store-v2.md), so copy them out and
`gunzip` them first.

Readers never see job runs. When a module has no snapshot yet, its page says the
data is being prepared (no error, no job wording) and fills in on its own once
the first run has installed data.

The **admin page** (`src/pages/Admin.tsx`, route `/admin`) is the same bundle
launched on the admin surface (`useAppSurface()`): a *Jobs* card with each job's
schedule in Beijing time, next run and last run (status as icon, word and
colour), a *Run now* button behind a confirmation dialog (focus starts on
Cancel; one `request_id` per opened dialog, reused for retries), and a *Run
history* list whose rows expand, animated unless reduced motion is requested,
to the run's log tail. Preview it with `?surface=admin` (below); the mock serves
the admin routes only for that view, like the service.

Open `http://127.0.0.1:5173/`. `dev/host.html` is a stand-in host using the
SDK's `createBridgeHost` in a sandboxed frame; `?path=/margin&dark=1&locale=en-US`
picks the start state, and `?surface=admin` opens the admin page. `dev/mock-backend.mjs` answers the `/v1` routes like the
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
| `GET /v1/{module}/dates` | viewer | snapshot dates, newest first |
| `GET /v1/{module}/summary?date=` | viewer | module summary |
| `GET /v1/{module}/rows?date=&page=&size=&sort=&order=&q=&f.<field>=` | viewer | one page of rows (size ≤ 200) |
| `GET /v1/{module}/rows/{code}?date=` | viewer | one row and its detail |
| `GET /v1/{module}/history/dates`, `history`, `compare`, `streak`, `counts` | viewer | cross-day queries over the history files (margin, panorama, etf; 404 for risk and sentiment); one at a time, 4 s limit, bounds in [docs/store-v2.md](docs/store-v2.md) |
| `GET /v1/admin/jobs` | admin view | each job: schedule slots, next run, last run |
| `GET /v1/admin/runs` | admin view | full run history with source (`schedule`, `bootstrap`, `manual`, `platform`), attempt, error code and installed outputs |
| `GET /v1/admin/runs/{id}/log` | admin view | last 64 KiB of the run's log, with a `truncated` flag |
| `POST /v1/admin/jobs/{job}/run` | admin view | Run now: body `{"request_id": "<uuid>"}`; 202 `{run, duplicate}` |

**Schedule.** The platform cannot yet originate tasks for a managed backend
(its `tasks/background` route is not reachable from a networkless container),
so the service keeps the pipeline's timetable itself, in Beijing time: marketdata Mon–Fri 21:00 with a 23:30 fallback; sentiment
00:40, panorama 00:50 and ETF 08:00 Tue–Sat; margin Mon–Fri 09:00 with a 09:50
fallback. A fallback runs only when no run of the job queued earlier that day
(scheduled or manual) succeeded or is pending. Each occurrence is one run with task ID
`schedule/<job>/<YYYY-MM-DDTHH:MM>`, so ticks and restarts never repeat it; on
start, each slot's latest occurrence in the past 20 hours runs once if it never
did.

**Bootstrap.** A fresh installation must not stay empty until the next slot. On
the first tick after start, each job whose output module (`sentiment`,
`panorama`, `etf`, `margin`) has no installed snapshot, and that has no run
queued or running and no scheduled occurrence that tick really queues (one whose
run already failed does not count), gets one run with task ID `bootstrap/<job>/<YYYY-MM-DD>` (the day in Beijing time).
The ID keeps it to one run per job per day: a restart the same day does not
repeat it, and a failed bootstrap is not resubmitted that day; it is tried again
only on the first tick after a process start on a later day. `marketdata` has
no module of its own; it bootstraps when `sentiment` or `panorama`, which read
the bars it updates, has no snapshot. Runs are queued as `marketdata`, then any
caught-up occurrences, then `sentiment`, `panorama`, `etf`, `margin`, and the
runner executes the queue one job at a time in that order (its queue holds 16).
`POST /v1/tasks/run` stays available to start a job by hand.

**Admin page.** The platform signs `"surface":"admin"` assertions only for the
app's admin view, after checking that the viewer administers the app (a Portal
admin or a user delegated the app); such a viewer need not be in the app's
audience. The `/v1/admin/*` routes answer 403 `forbidden` to anything else,
reader assertions included. Reader data routes also accept admin assertions: the
dashboards are the app's only data and are not audience-sensitive. Job runs are
no longer served to readers (`GET /v1/runs` is gone).

*Run now* queues the job as `manual/<request_id>` with the occurrence
`manual:<request_id>`. The request ID names one click: the same ID again returns
the same run with `duplicate: true` and never queues twice (404 for an unknown
job, 409 `queue_full` when the queue is full). A manual run counts for the
scheduler's fallback rule like any other run of the job that day.

Viewer routes verify the `X-Portal-Assertion` against the current
registration, boot and request URI, and refuse cookies and authorization
headers. Responses stay under the relay's 1 MiB limit, which is why rows are
paged. A task only queues a job: jobs (`marketdata`, `sentiment`, `panorama`,
`etf`, `margin`) run one at a time inside the container with per-job time
limits, and their snapshot and history outputs are validated and installed by
the service. Storage layout and rules: [docs/storage.md](docs/storage.md) and
[docs/store-v2.md](docs/store-v2.md) (the current format, `data_format: "2"`).

**Disk.** A day's snapshots take about 4.4 MB gzipped and history 0.5 MB, so
the data volume grows about 1.1 GB a year in snapshots (kept 365 days), 0.14
GB a year in history (kept forever) and 0.3 GB a year in `work/`, on top of
about 0.75 GB after seeding. Give the installation a **6 GiB** quota at
install (the default 3 GiB is reached in about two years). The service logs a
warning when `/data` use passes 80 % of its quota.

The backend container has no network (Portal doc 174). The service starts the
reviewed forward proxy's forwarder (`packages/proxy`, `egress.go`) on
`127.0.0.1:3128` before any job runs, and the runner points the workers'
`HTTPS_PROXY` at it (`HTTP_PROXY` is not set, so sources must be `https://`).
Jobs that fetch data work once an administrator has reviewed the hosts the
descriptor suggests in `network_proxy.hosts`; until then every CONNECT is
refused with 403 and `X-Portal-Proxy-Refusal`. The data server's upstream
quotes API is reached at `https://quotes.internal.anchan.kazuhahub.com` (an HTTPS name in
front of the API, which used to be addressed as plain `http://47.237.204.217:8000`
and so could not go through the proxy); `QUOTE_API` overrides it. The
`marketdata` and `panorama` jobs need that host reviewed like the others.

```sh
cd apps/kazuha-hub-market-monitor/service && go test -race ./...
```

## `pipeline/mm_job.py` — the job entry

The service runs `mm_job.py <job>`. It copies the pipeline code into
`/data/work` (the pipeline's install prefix and `HOME`; data there is kept),
clears locks a killed run may have left, starts the pipeline's data server
(`stock_server`, loopback port 8091) for the jobs that need it, runs the
pipeline's own script unchanged, and converts the output **this run wrote**
into snapshot documents, plus a `<module>.history.parquet` of curated columns
for margin, panorama and etf (pyarrow, explicit schema; the service refuses
the whole run if one is missing or invalid). Output older than the run is
refused, so a pipeline that skips and exits 0 never republishes old data.

| Job | Pipeline script | Data server | Snapshots |
| --- | --- | --- | --- |
| `marketdata` | `MarketData/update.sh` | yes | none (updates the bar store) |
| `sentiment` | `workspace/analysis/sentiment_daily.py` | no | `sentiment`, `risk` |
| `panorama` | `workspace/panorama/daily_update.sh` | yes | `panorama` (+ history) |
| `etf` | `workspace/analysis/panel/refresh.sh` | no | `etf` (+ history), `risk` |
| `margin` | `margin_scan/update.sh` | no | `margin` (+ history), `risk` |

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
`MM_SNAPSHOT_DIR=<dir> go test -run TestSnapshotsFromARealRun ./...`, where
`<dir>` holds `<module>.json` and, for margin, panorama and etf, the job's
`<module>.history.parquet` (a staging directory of `mm_job.py`); snapshots
copied out of `/data` are gzip files and must be gunzipped first (a module
without a history file is then only checked as a snapshot).

Still to verify once the platform provides egress: with the data server up,
Panorama's freshness check compares the last bar with the calendar's
previous trading day; an evening run after that day's bars are written must
pass.

Known limit: when every ETF feed fails, `refresh.sh` recomputes from its
stored data and exits 0, so the ETF snapshot can carry an older `as_of`;
its `summary.data_health` shows each source's last date.

## Backend image

```sh
docker build --platform linux/amd64 -f apps/kazuha-hub-market-monitor/service/Dockerfile -t market-monitor .
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
2. Review the proxy hosts in an installation and verify the jobs end to end
   (done in code: the forwarder is wired and the `http://` source is now
   `https://`, and the data server's upstream is reached by its HTTPS name
   `quotes.internal.anchan.kazuhahub.com`). Only the installation's host review is left.
3. Panorama: the industry breakdown, market medians and valuation shifts
   come from the export step's page data (`site/data.js`), used only when
   that run wrote it for the same date; see `convert_panorama`.
