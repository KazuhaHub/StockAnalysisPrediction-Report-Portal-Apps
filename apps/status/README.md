# Status application

Status is an independent application in the shared
[Portal Apps repository](https://github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps).
It has two lines, and this branch holds the second:

- **Legacy line, `0.1.0-beta.4`** (`app.json`, on `main`). An installable sandboxed
  ZIP plus a separately deployed Go service with its own SQLite database. It is
  paired to Portal through a generic backend connection, and it has its own
  offline backup and restore. The verified marketplace continues to select
  published Beta.3 until the new immutable artifacts are verified. The minimum
  verified Portal release is `v2026.43.2`. The runbooks in `docs/` describe this
  line.
- **Platform v2 line, `0.2.0-beta.1`, draft** (`app.v2.json`, this branch). A fresh
  install on the new Portal app platform. Nothing is released, no package is
  built yet, and the legacy release, container and browser checks do not run here.

An app folder holds one manifest, so on this branch the legacy `app.json`,
its flags and its release tooling are absent. The sections below describe the v2
line unless they say "legacy".

## Platform v2 port (0.2.0-beta.1, draft)

`app.v2.json` declares the application for the new Portal app platform. It is a
fresh install, not an upgrade of `0.1.0-beta.4`, and nothing here is released.

- The service listens only on the Unix socket named by `PORTAL_APP_HTTP_SOCKET`.
  It answers `POST /v1/handshake` and `GET /health/ready`, and verifies the
  viewer assertion on the `/v1/*` routes the browser relay forwards. There is no
  TCP listener, pairing file or storage-key flag.
- The viewer is the platform's opaque subject, OU identifiers and role. Grants
  are bound to one installation and are re-entered after a reinstall.
- The platform owns backup and restore of `/data`. When the data was written
  under a different installation or controller epoch, probes and notification
  delivery stay paused until an administrator reviews the queue and resumes.
- The backend has no network. Until the platform grants a background network
  path, probes report the unknown outcome `egress_unavailable` and queued
  notices stay queued. Nothing is reported as healthy or failed because of it.
- The frontend uses `AppRoot`, `useAppBackend` and `useAppPage`. `public-src`
  is parked: it is not part of the v2 build.
- Not possible yet, because Portal has no route for it: background probes and
  notifications (no egress for the background identity), the anonymous public
  page (the platform socket serves no `/`, `/public/v1/*` or `/readyz`), inbound
  heartbeats (no ingress), and picking other Portal users or OUs for a grant (no
  principal directory). The code for the public page and heartbeats stays in the
  service, unregistered, for the phase that adds those routes. The editor offers
  neither public options nor the heartbeat kind, and shows an existing heartbeat
  monitor read-only.
- Grant principals are `user:` or `ou:` followed by the 64 lowercase hex
  characters the platform supplies. The service stores its credential-sealing key
  as `status.key` beside `status.db` and refuses to start if the database exists
  without it; restore both together.
- The database shape and the credentials table are unchanged. Moving them to
  platform custody needs an approved schema first.

## Features

- Multiple components and HTTP, Dify read-access, PostgreSQL `SELECT 1`, DeepSeek
  balance, Alibaba/Qwen account billing and authenticated heartbeat monitors. On the
  v2 line none of these can run yet (see below), and heartbeat monitors cannot be
  created.
- Current account/OU read grants and a separate financial-information grant.
  Saved credentials are sealed and never returned through a read API.
- Single-owner storage, four probe workers, per-monitor/credential leases,
  revision fencing, freshness, confirmation thresholds and incident transitions.
- Legacy line only: independent public component labels and separately published incident narrative.
  Public output is disabled until explicitly enabled and contains no amounts,
  targets, grant references, account identifiers or private incident detail.
- Durable immutable notification outbox using dedicated per-component Portal
  publishers, with namespace verification before publishing. Portal owns inbox,
  Email, Slack and Webhook delivery. Portal capture is not recipient delivery.
- Legacy line: offline snapshot/restore with key verification, rollback backup,
  paused work and explicit queue review before resume. Reinstall/Portal restore
  require re-pairing. The v2 line has no backup, restore or pairing of its own: the
  platform restores `/data`, and work then starts paused until an administrator
  resumes it.
- English, Simplified Chinese and Traditional Chinese private/public frontends.

## Build and validate

Run from the monorepo root. `python3 scripts/catalogue.py package status` and the
ZIP described after the commands belong to the legacy line; the v2 package comes
from the v2 packaging step (OCI image export, `scripts/build-app-v2.py`, offline
envelope and licence scan), which is not part of this branch yet.

```sh
npm ci
python3 scripts/plugin-standard.py
npm run typecheck
npm run test:sdk
npm run test:status-ui
node --test apps/status/frontend/tests/*.test.cjs
python3 scripts/build-status-frontend.py
python3 scripts/catalogue.py package status
cd apps/status/service
GOWORK=off GOTOOLCHAIN=go1.26.11 go build ./...
GOWORK=off GOTOOLCHAIN=go1.26.11 go vet ./...
GOWORK=off GOTOOLCHAIN=go1.26.11 go test -race ./...
GOWORK=off GOTOOLCHAIN=go1.26.11 go run golang.org/x/vuln/cmd/govulncheck@v1.8.0 ./...
```

On the legacy line the ZIP is `dist/status/0.1.0-beta.4/status.zip` with a SHA-256 sidecar. It contains only
`app.json`, the root HTML and built static assets. Source tests and credentials do
not enter the archive. Public service assets are embedded and deterministically
rebuilt by the same script. A classic script is intentional: a null-origin iframe
cannot load same-origin ES modules through CORS without weakening its isolation.

For browser acceptance, install `apps/status/tests` dependencies and Chromium,
set `PORTAL_BINARY` and `STATUS_BINARY` to separately built binaries, then run
`npm --prefix apps/status/tests test`. Fixtures create fresh temporary databases,
accounts and random keys and delete them afterward. A private network interface
is required; tests do not introduce a loopback exception into production policy.
No billable provider call or real external notification is needed.

## Operator documentation and remaining acceptance

- [Install, configure, pair and operate](docs/operator-guide.md)
- [Upgrade and rollback the React UI release](docs/upgrade-react-ui.md)
- [Approved storage and recovery decision](../../docs/storage-proposal.md)
- [Platform contract](../../docs/platform-contract.md)
- [Full implementation plan and exit gates](../../docs/implementation-plan.md)

The Beta's verified scope, optional configuration and remaining manual audits are
recorded in [the readiness decision](../../docs/status-0.1.0-beta.4-readiness.md).
The historical S00-S11 audit remains evidence of the wider plan; it is not a
requirement to provision every third-party account before installing this release.
