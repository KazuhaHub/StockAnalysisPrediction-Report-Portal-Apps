# Implementation evidence

## Baseline (2026-10-22)

- Shared repository name confirmed: StockAnalysisPrediction-Report-Portal-Apps.
- Owner selected public visibility.
- Portal notification PR #141 is open, mergeable and unmerged at inventory time.
- Portal default market remains its `apps/index.json`; no production override or
  production database was inspected. The market initially contains demo-symbols.
- Existing iframe isolation and bridge do not provide private external OU identity.
- Status and generic Portal connection storage proposal awaits explicit approval;
  no schema code or database has been created by the bootstrap.

## Work package status

S00 inventory in progress. S01 platform connection contract/storage is being
prepared. S02 repository bootstrap is independent preparatory work. S03-S11 remain
outstanding. No Status feature, live provider check or deployment is claimed.


## Bootstrap verification

- Catalogue/packaging tests: five tests passed; rebuilt demo ZIP has deterministic
  metadata, root manifest/entry, bounded assets and a SHA-256 sidecar.
- Shared request-bound assertion protocol: tests failed before implementation,
  then passed with race detection and vet. Replay storage is bounded and fails
  closed. This is a library, not a deployed Portal integration.
- Dify read probe verified against official current API documentation: authenticated
  `GET /v1/info` proves application-key/read access without running a workflow.
  Reference: https://docs.dify.ai/en/api-reference/guides/get-started
- DeepSeek account balance API verified against official documentation:
  https://api-docs.deepseek.com/api/get-user-balance/
- Alibaba billing account balance uses separate RAM authorization; the documented
  action is `bss:DescribeAcccount` (official spelling). This does not report an
  individual Qwen key's model quota. Reference:
  https://help.aliyun.com/en/user-center/developer-reference/api-bssopenapi-2017-12-14-queryaccountbalance
- Deployment-specific Dify version, Qwen account/site/credentials, installed Portal
  version and custom market override remain unverified. No production access was
  attempted and no genuine upstream credential is stored here.


## Published bootstrap and protocol work

The public repository was created and its bootstrap pushed on 2026-10-22. The
Portal default market URL and every deployment override remain unchanged.
Pinned legacy demo archive availability and its manifest ID/version/scopes were
verified over HTTPS; Python's local CA configuration failed, so the download was
verified with the system curl trust store without disabling TLS verification.

Seven catalogue/package tests now pass, including regressions that failed before
fixes for symlinked asset roots and release-tag/asset identity mismatch. The shared
protocol additionally provides a signed challenge/answer boot handshake, request
nonce replay protection and current-boot binding. A backend restart cannot accept
an assertion signed for the prior boot. Transport policy tests cover segment
boundaries, DNS pinning/mixed answers, private-network permission, reserved/metadata/
translation ranges, redirects, size limits and malformed JSON. These are reusable
library foundations; the Portal proxy is not wired or deployed yet.

Pending owner input: exact Portal/Status schema proposal. No schema code has been
written and no Status database was initialized. Complete S01/S02 implementation
continues after that decision. The full objective remains incomplete.


## Current viewer snapshot (2026-10-22)

The Portal branch now has an internal read-only account/OU projection primitive,
without routes or new tables. New tests first failed for the missing projection;
an invalid-expiry regression failed before fail-closed validation was added.
SQLite, focused race and real PostgreSQL cases prove current OU/role resolution,
account activation/expiry/password/session/deletion fencing, registration-bound
opaque identities and invalid ancestry/default refusal. Panel civil-date expiry
and cancelled context are covered. Full Go suite/build/vet/staticcheck passed.

This does not complete S01: token issuance still needs the current account cursor,
installation-generation checks and backend registry/proxy wiring. Exact storage
approval is still pending and no migration is written. The app-repository protocol
PR #1 head 28ee089 has passing GitHub Actions catalogue/protocol jobs. Production
market configuration, provider credentials and runtime have not been touched.


## Toolchain security gate

Portal draft PR #142's first go-test job stopped at govulncheck for standard-library
GO-2026-6809 under Go 1.26.9, before running its test suite. The minimum toolchain
in both Portal and the shared protocol module is now Go 1.26.10. The shared module
also gains the same govulncheck CI gate. Local scans with that exact compiler
report no reachable vulnerabilities; shared-module race tests and vet pass.
This does not approve or implement new storage. Owner schema approval remains
required before the dependent connection/persistence packages can proceed.


## Approved storage implementation (2026-10-22)

The owner explicitly approved Option A, including the exact table layout and
restore/deletion principles. This supersedes the pending-approval statements in
historical entries above. No additional storage decision is inferred.

Portal PR #142 now implements migration 0008, paired generic connection CRUD/UI,
app-bound capability/identity checks, pinned-transport boot handshake and a
paginated administrator principal directory. Commit 55db11f5 has passing GitHub
Actions Go/PostgreSQL, focused race, web and image checks. The platform also gains
a read-only notification publisher-identity endpoint and safe backend-conflict
handling; final verification of those additions is tracked separately.

The Status development package now has the approved independent SQLite schema,
single-owner volume lock, credential sealing, verified offline backup/restore,
private/public API boundaries, component and finance grants, monitor configuration,
four-worker leased scheduling, provider adapters, incident/outbox transactions,
maintenance, retention and reviewed resume. Its three-locale sandbox frontend is
packaged locally and the separate public page uses explicit DTOs. Gateway and
container templates plus the operator runbook are in apps/status.

Tests were added before the corresponding implementation. Service race tests,
CLI backup/restore checks, exact-decimal balance fixtures, official ACS3 fixed-input
signature vector, heartbeat replay and publisher destination fences pass locally.
A reachable x/text advisory found by govulncheck was fixed by pinning v0.42.0;
the follow-up scan reports no vulnerabilities. Browser acceptance uses real local
Portal and Status binaries, fresh temporary databases/accounts/random keys and an
explicit private interface. Three scenarios pass: disjoint OUs/current membership,
multiple-monitor admin save with directory refresh, and a signed-out public prefix
page without private labels (including narrow mobile layout). Tests found and
fixed duplicate refreshes and native form submission blocked by the unchanged
iframe sandbox. No real provider request or recipient notification was used.

The full objective remains incomplete. Outstanding gates include accurate partial
boundary/unobserved uptime accounting, public history/freshness, maintenance-exit
and restart evidence, explicit test controls, full failure/recovery drills,
container/gateway runtime validation and independently versioned immutable release
and catalogue rollout. Status stays at 0.1.0-dev and out of the production index.
Production credentials, deployment and marketplace settings remain untouched.


## Development review and first complete CI (2026-10-22)

Draft application PR #2 is open against the shared protocol foundation. At head
636db6f, all five GitHub Actions jobs passed: catalogue, protocol, Status service
checks, real Portal/Status browser acceptance and development container smoke.
The container was built and exercised as a non-root user, including readiness,
default-private output, offline backup/restore and retained rollback snapshot.
The browser job pins Portal platform commit b4eabb4f and uses isolated fixtures.
These results do not publish an image/release or migrate the production catalogue.

A subsequent failing maintenance-exit regression demonstrated that an observation
made inside maintenance could retain a green state afterward. The reducer and
snapshot now require two fresh post-maintenance observations; interval accounting
also refuses to extend old healthy evidence past the maintenance boundary. The
service race suite passes after this fix. Partial-hour/unknown/paused-time history
and the other explicit acceptance gaps remain open.


## History precision and public timeline (2026-10-22)

Added versioned observation evidence within the approved JSON field; no schema
change. Partial UTC buckets now clip actual intervals and distinguish observed,
unknown and excluded milliseconds. Pauses and overlapping maintenance use a
single union; missing evidence and expired samples cannot become healthy time.
Private history includes a coverage summary and coarse hourly strip. Explicitly
published public history has its own visibility gate and only coarse intervals.
Both pages display actual observation freshness separately from page generation.

Failing regressions exposed same-millisecond control ordering, restore rewriting
prior evidence and future maintenance prematurely resetting current state. The
fixes preserve commit order, finalize evidence before restore invalidation and
leave future maintenance to its actual boundary. Targeted and full race tests
pass. The real browser suite covers private/public history interaction; final
post-fix verification is recorded with the development commit. Historical
maintenance-edit/retention edge cases and all other ledger gates remain open.


## Notification recovery and audience drills (2026-10-22)

The history commit 09ff928 passed all five CI jobs. Additional service race tests
now exercise reopening the database with an unacknowledged publication lease,
waiting for expiry and retrying identical occurrence/payload with a new lease.
Stale acknowledgements are refused. A restored uncertain publication remains
review-required after resume, cannot reuse a rotated publisher revision, and can
be explicitly discarded without losing immutable reconciliation evidence.
A storm of eleven transitions preserves every transition, publishes five notices
and records six suppressions within the component's hourly bound.

Four real Portal/Status browser scenarios pass locally. The added scenario creates
two independent component publication tokens and exact OU inbox rules. Each OU
sees only its event; a retry returns the original ID, changed content returns 409,
and removing an account from its OU revokes access to the old notification.
Only isolated fixture accounts and internal inboxes are involved. Full external
channel timeout/quota drills and the other acceptance gates remain open.


## Scheduler interruption and explicit check controls (2026-10-22)

A failing restart regression exposed silent relaunch of expired probe leases.
Recovery now records one unknown observer-unavailable observation at the expired
lease boundary, resets confirmation streaks, preserves elapsed history and delays
the next due time by the configured interval/jitter. Recovery is bounded to one
abandoned check per scheduler tick. Late results cannot apply to the new lease.

Added an administrator-only request for a check of saved monitor configuration.
It uses current revision/lease/enabled checks, refuses global pause and throttles
repeated requests to 30 seconds using the existing audit ledger. It queues through
the existing worker/credential limits and never returns synthetic success.
The sandbox editor includes the control and all three locales explain queued
semantics. Full race tests, vet/build and four real browser scenarios pass;
the browser check verifies a manual request cannot bypass global pause.
Notification acceptance commit d14d557 passed all five CI jobs. No new schema or
production configuration changes are involved.


## Gateway runtime acceptance expansion (2026-10-22)

Expanded the isolated container smoke to run the actual nginx public template
against the real Status image on a dedicated temporary network. It exercises
public HTML/assets/status/incidents/history and refusal of management, handshake,
heartbeat and readiness paths through the public prefix. Fixture publication is
seeded offline after the restore drill; no production data/configuration is used.
Both containers run without capabilities, with read-only filesystems. Local Docker
is unavailable, so runtime evidence is pending the container CI job; syntax
compilation alone is not considered acceptance.


## Explicit capability results and verified gateway (2026-10-22)

All five CI jobs passed at 05787ac, including a real nginx gateway using the
public deployment template. The read-only non-root gateway scratch paths were
made explicit after the first runtime drill exposed startup failure.

Alibaba NotApplicable now persists an explicit unsupported observation outcome,
while the display state remains unknown. It cannot close an existing outage.
The private DTO exposes the bounded outcome and strips internal evidence metadata
and absent financial values. All three UI locales explain unsupported billing,
missing permission, wrong site, missing currency, authentication failure, observer
failure and stale evidence. Five frontend contract tests, full service race tests
and four real browser scenarios pass locally. No real provider call was needed.


## Billing identity and anonymous budgets (2026-10-22)

Billing configuration now requires an operator-reviewed local account reference in
the existing versioned monitor JSON. Active keys for one provider/account cannot
create separate component balance pools; same-component currency projections are
kept separate and duplicate currencies/inconsistent sites are refused. Provider
APIs cannot automatically establish the funding relationship of arbitrary keys;
the UI/runbook require the administrator to verify account ownership. No new
column or table was added.

Anonymous reads now have bounded per-socket-peer and global token budgets, with a
hard origin registry cap and idle eviction. Spoofed forwarding headers do not
allocate new budgets; 429 includes retry guidance, and private auth remains
independent. Tests cover bursts, global work, registry bounds and expiry. The
runbook explains trusted-gateway client limits and the shared proxy budget.


## Transient quota and billing-observation failures (2026-10-22)

New regressions exposed transient publication identity-preflight 429/5xx being
misclassified as permanent audience conflicts. These responses now retry with the
same event identity; failed credentials or an actual namespace mismatch still
require review. Numeric/date Retry-After is bounded to one hour and persists via
existing next-at fields for both probe and publication retries. Tests cover
preflight quota, post-capture endpoint quota, unchanged event payload/occurrence,
retry delays and malformed/oversized/date hints.

DeepSeek/Qwen transport failures and DeepSeek authentication/server errors now
remain unknown observations instead of accumulating exhausted-credit outages.
These paths never produce an inferred financial value. Service race and vet
checks pass after the fix. External real-recipient delivery remains unexercised;
all publication/probe fixtures are isolated and non-billable.
