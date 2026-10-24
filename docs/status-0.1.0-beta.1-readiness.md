# Status 0.1.0-beta.1 release scope and readiness

## Install first, configure afterward

On 2026-10-24 Pacific the owner explicitly directed that Status be published and
brought online before provider credentials are configured. This supersedes the
historical plan's coupling of optional live-provider acceptance to distribution.
The decision authorizes publication in the shared Apps marketplace and deployment
to the existing Portal environment. It does not claim Qwen billing authorization,
external recipient approval or completion of every S00-S11 deployment exercise.

This is an initial Beta, not a declaration that every third-party integration has
been provisioned. Install the immutable frontend through the real market, deploy
the matching independently versioned backend, pair them privately, then configure
monitors, credentials, audiences and notification destinations in the application.
Do not require Qwen credentials merely to download, install or open Status.

## Provider capabilities

The release implements HTTP, authenticated Dify info, PostgreSQL SELECT 1,
DeepSeek account balance, Qwen account billing and signed heartbeat adapters.
Missing information never fabricates success, a zero balance or healthy uptime.
A fresh application contains no monitors or credentials. The empty overview
explains that administrators configure monitoring and viewing permissions in Manage.

The actual target Dify read-only info and DeepSeek balance checks succeeded at
2026-10-24T03:23:03Z, without inference or secret disclosure. PostgreSQL's explicit
local Unix transport succeeded with a scoped role at 06:17:21Z, with negative
password/database/port controls and no network or additional persistent container.
Details and protected receipt locations are in the
[acceptance ledger](../apps/status/docs/acceptance.md) and
[local transport runbook](../apps/status/docs/postgresql-local-socket.md).
Qwen signing, capability and permission failure behavior has fixture coverage;
actual RAM account/site access remains unconfigured. The owner or account
administrator will provision the credential after installation. A DashScope model
API key is not used as a billing credential.

## Authority and isolation

The current account/OU assertions, separate finance grants and default
administrator-only configuration are covered by shared protocol, Portal and Status
negative tests and real released-Portal browser scenarios. Account recreation,
OU movement, token revocation, disable/reinstall/uninstall and unpaired startup are
exercised. The service and SQLite storage remain outside Portal. No run-analysis,
queue or report page is modified. Read the [platform contract](platform-contract.md)
and [storage decision](storage-proposal.md) for the approved boundaries.

Fresh storage has no components, public projection disabled and probes/outbox
paused. Pairing does not grant ordinary users visibility into nonexistent or
ungranted components. Initial `/status` uses the authenticated Portal app redirect;
public projection is a later explicit operator choice. No real email, Slack or
Webhook delivery is authorized by this release decision.

## Storage recovery and fault drills

Go race tests and the ledger cover exclusive storage ownership, sealed
credentials, wrong keys/future schemas/missing products, snapshot and isolated
restore, paused work after restore, queue fingerprints and uncertain publication
review. The target candidate backup/isolated restore receipts are retained under
the protected deployment directory documented in the ledger. This is not a claim
of off-host disaster recovery or restoration of live third-party accounts.

The required failure matrix is recorded in the
[requirement audit](../apps/status/docs/requirement-audit.md): provider failure,
stale observations, database deadlines, lease recovery, Portal/Status outages,
notification acknowledgement loss and public projection boundaries. Actual process
stop/restart and scheduled checks are exercised in browser integration; local
notification capture and a signed fixture receiver are exercised separately.
Fixture recipients do not imply actual SMTP/Slack acceptance.

## Accessibility

Fifteen browser scenarios passed against released Portal v2026.43.4. The minimum
published v2026.43.2 is independently exercised by CI. Coverage includes automated
WCAG A/AA checks, localized labels, keyboard controls, light/dark themes, narrow
320-pixel layouts, enlarged text and long labels. Manual screen-reader and native
browser zoom certification remains unverified and is disclosed as a Beta limit.

## Operator review and publication evidence

Apps PR #7 merged as `243bd3a54e173cd91df24dad3c939651ee2c57d4`; exact-main CI
[40070890033](https://github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/actions/runs/40070890033)
passed all twelve jobs. The runtime digest selected here was pulled and exercised
by that run's prebuilt image path:
`gcr.io/distroless/static-debian12:nonroot@sha256:afa5c872c891853ca7fcf1f12c3edb23f7eeef36189728842dd51042ff57f7ab`.
The release preparation changes only version metadata, empty-state explanation and
this installation/configuration boundary. No schema change or new privilege is
introduced. The owner's current deployment instruction is the operator decision;
it is not represented as completed credential or recipient verification.

The guarded release workflow must still pass exact-source main CI, download and
verify the minimum released Portal, run browser/notification integration, build all
six archives, compare both image executables, and verify immutable public assets.
Only after successful publication and download verification may the catalogue
include Status. Then verify the actual market install, private pairing, healthy
service and authenticated `/status` route. Keep optional monitors and notification
routes unconfigured until the operator chooses their targets and credentials.
