# Status application

Status is an independent application in the shared
[Portal Apps repository](https://github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps).
Its frontend is an installable sandboxed ZIP. Its Go service owns a separate
SQLite database and never opens the Portal database. The Portal supplies current
viewer/OU identity through its generic paired backend connection.

This is a development build (`0.1.0-dev`), excluded from the production catalogue.
The platform dependency is [Portal PR #142](https://github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal/pull/142),
stacked on notification PR #141. Neither dependency is claimed deployed.

## Implemented development surfaces

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
node --test apps/status/frontend/tests/*.test.cjs
python3 scripts/build-status-frontend.py
python3 scripts/catalogue.py package status
cd apps/status/service
GOWORK=off GOTOOLCHAIN=go1.26.10 go build ./...
GOWORK=off GOTOOLCHAIN=go1.26.10 go vet ./...
GOWORK=off GOTOOLCHAIN=go1.26.10 go test -race ./...
GOWORK=off GOTOOLCHAIN=go1.26.10 go run golang.org/x/vuln/cmd/govulncheck@v1.8.0 ./...
```

The ZIP is `dist/status/0.1.0-dev/status.zip` with a SHA-256 sidecar. It contains only
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
- [Approved storage and recovery decision](../../docs/storage-proposal.md)
- [Platform contract](../../docs/platform-contract.md)
- [Full implementation plan and exit gates](../../docs/implementation-plan.md)

The implementation is not yet a released or fully accepted Status product. The
remaining acceptance audit must cover partial-hour/unobserved uptime accounting,
maintenance-exit evidence, retention/recovery edge cases, operator test controls,
public history/freshness, full browser workflows, container/gateway runtime and
immutable release/catalogue migration. Provider fixtures and official signing
vectors do not replace deployment-specific Qwen billing authorization checks.
