# Status application

Status is an independent application in the shared
[Portal Apps repository](https://github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps).
Its frontend is an installable sandboxed ZIP. Its Go service owns a separate
SQLite database and never opens the Portal database. The Portal supplies current
viewer/OU identity through its generic paired backend connection.

Status `0.1.0-beta.4` is the SDK 0.2 release candidate. The verified marketplace
continues to select published Beta.3 until the new immutable artifacts are verified. Deploy and pair the application
before configuring optional providers. New installations have no components or
credentials; monitoring and notification delivery remain paused until configured.
Provider configuration is not a requirement for downloading or installing the app.
The minimum verified Portal release is `v2026.43.2`.

## Features

- Multiple components and HTTP, Dify read-access, PostgreSQL `SELECT 1`, DeepSeek
  balance, Alibaba/Qwen account billing and authenticated heartbeat monitors.
- Current account/OU read grants and a separate financial-information grant.
  Saved credentials are sealed and never returned through a read API.
- Single-owner storage, four probe workers, per-monitor/credential leases,
  revision fencing, freshness, confirmation thresholds and incident transitions.
- Independent public component labels and separately published incident narrative.
  Public output is disabled until explicitly enabled and contains no amounts,
  targets, grant references, account identifiers or private incident detail.
- Durable immutable notification outbox using dedicated per-component Portal
  publishers, with namespace verification before publishing. Portal owns inbox,
  Email, Slack and Webhook delivery. Portal capture is not recipient delivery.
- Offline snapshot/restore with key verification, rollback backup, paused work and
  explicit queue review before resume. Reinstall/Portal restore require re-pairing.
- English, Simplified Chinese and Traditional Chinese private/public frontends.

## Build and validate

Run from the monorepo root:

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
GOWORK=off GOTOOLCHAIN=go1.26.10 go build ./...
GOWORK=off GOTOOLCHAIN=go1.26.10 go vet ./...
GOWORK=off GOTOOLCHAIN=go1.26.10 go test -race ./...
GOWORK=off GOTOOLCHAIN=go1.26.10 go run golang.org/x/vuln/cmd/govulncheck@v1.8.0 ./...
```

The ZIP is `dist/status/0.1.0-beta.4/status.zip` with a SHA-256 sidecar. It contains only
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
