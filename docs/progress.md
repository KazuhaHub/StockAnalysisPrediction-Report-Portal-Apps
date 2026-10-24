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


## Retrospective maintenance and retention boundaries (2026-10-22)

Failing tests found that whole-hour aggregates ignored maintenance recorded after
an interval and cleanup dropped an hour still overlapping the 90-day boundary.
Corrected hours now rebuild from retained raw evidence; expired evidence yields
exact maintenance exclusions and unknown remaining coverage, never a proportional
allocation of aggregate health. The reconstruction fetches bounded evidence once
per monitor and clips it per bucket, avoiding one database scan per corrected
hour. A 2,000-observation regression covers ranges beyond a single bucket limit.
The overlap hour survives cleanup. Full service race/vet/build checks pass.


## Sandbox form recovery and theme workflows (2026-10-22)

A real-browser failing regression showed invalid configuration submissions erased
unsaved component/monitor fields. Errors now preserve the existing form and focus
an alert; busy mutations guard duplicate actions and restore prior control state.
Safe HTTP statuses map to localized actionable messages without upstream text.
The operations page now loads at most two backend requests concurrently, matching
the Portal's app connection budget.

Five real Portal/Status browser scenarios pass: the new workflow covers operations
loading, dark theme, all three languages and keyboard navigation; the component
scenario covers an invalid target, retained multi-monitor fields, correction and
successful save. Six frontend contract tests pass. Historical boundary commit
b390adf passed CI. These checks are specific workflow evidence, not a blanket
accessibility certification or final production acceptance.


## Generic HTTP response conditions (2026-10-22)

Requirement audit identified missing first-release HTTP status/body conditions.
Added optional exact status and bounded literal text matching in the existing
monitor config JSON and sandbox editor. Defaults remain 2xx, with the same bounded
read-only GET transport. Oversized bodies, redirects and quota responses cannot
be made healthy by a custom condition; response bodies are not persisted.
Tests cover match/mismatch, empty 204, oversized responses and invalid/provider
configuration. Full race/vet/build and the real multi-monitor editor workflow
verify the new saved condition. No schema change is involved.


## Independently versioned service artifact candidates (2026-10-22)

Added a builder producing one app-qualified directory with the sandbox ZIP,
selected pure-Go service archives, exact version/source metadata and complete
SHA-256 list. Output replacement is refused. Archive timestamps/ownership and
compiler host paths/build IDs are normalized. A native macOS arm64 candidate
executes with the expected manifest version; hashes validate and a repeated
build produces byte-identical service archive bytes. Nine Python tooling tests
pass, including archive contents/metadata and target validation.

Six-target CI now builds/checks candidates and executes the native Linux version.
It uploads temporary CI artifacts only. The publication guide preserves gates for
released Portal dependencies, a real minimum version, clean reviewed commits,
immutable app-qualified tags/assets, image digest verification and catalogue
migration. No public release/tag/image or market change has been made. Cross-build
CI evidence is pending; local native success alone does not prove every target.


## Authorized component detail, paging and export (2026-10-22)

Added private component pagination/search with SQL authorization before counts and
limits, exact-ID detail lookup and a bounded 512-KiB JSON snapshot/history export.
Current finance grants control exact balance projection; target configuration,
credential references and internal observation metadata never enter the export.
Tests cover 64 mixed-OU components, second-page totals, hidden search/detail,
revoked OU exports, limit validation and finance grant changes.

The overview includes search/page controls, observation detail and selectable
export text without widening iframe sandbox downloads. Visible idle read views
poll every 30 seconds; admin forms, active text entry and prepared exports are
preserved. Full service race/vet/build and all five real browser scenarios pass,
including exported JSON parsed from the installed sandbox and private target
redaction. All six artifact target CI jobs passed at 8d580d9; complete run status
remains tracked separately from individual job completion.


## Configurable retention, recovery refusal and public paging (2026-10-23)

The existing approved settings ledger now holds bounded raw/history retention
periods, edited through Operations. Defaults remain 30/90 days; raw is 1–30 and
history is at least raw through 90. Cleanup reads the policy inside its transaction
and preserves active/pending evidence and overlapping boundary hours. Race tests
and installed-UI save/readback cover bounds, persistence and actual cutoff work.
No DB columns, tables or migrations were added.

Recovery drills reject wrong-key, future-schema, missing-index and occupied
rollback candidates while proving the live database remains readable/writable and
candidate pause values do not leak into live state. Public component lists now
have filtered totals/limits and independent component/incident pager controls.
Service tests cover global-default closure, explicit publication filtering and
page bounds. The prior 0ff87f6 head passed full CI including all six artifacts.


## Runtime capability agreement and reviewed first start (2026-10-23)

The private frontend now verifies versioned component/history/export/retention
capabilities before requesting component data. A real-browser fixture returning
an older identity-only response is refused with an upgrade message and no data
request; deploying a matching response and refreshing recovers. Seven frontend
contract tests and six real-browser workflows cover this boundary.

New databases start with probes/outbox paused and public access closed. Bootstrap
pause has an audit anchor so history excludes it. Reviewed probe-only resume does
not start publication, and existing stores preserve their configured pause flags.
Default-start behavior is tested separately from explicitly active store fixtures.
Full service race/vet/build passes. No schema product/version was changed; these
are bootstrap values in the approved settings/audit products.


## Authorized target deployment preparation (2026-10-23)

Read the existing operator notes and verified the actual target over SSH instead
of applying the repository's generic Portal Compose template. The live Portal is
v2026.43 in its existing deployment directory. The required notification/platform
APIs are not deployed. Both dependency branches now integrate main `65c18abb`,
preserving its released migration prefix and appending 0007/0008; their exact-head
CI remains separate from local integrated validation. The integration passed full
Go tests/vet/build, PostgreSQL tests, focused extension/migration race tests, 1212
frontend tests/typecheck/build and all six real-browser workflows.

Built the a4ffec6 Linux candidate and verified its archive/ZIP checksums on the
target. Installed a dedicated non-root/read-only local image and a separate
profile-gated private Compose candidate. Initialized the approved independent
store with paused probes/outbox, protected the generated storage key, verified an
initial backup by restoring into a separate database, and ran an isolated fixture
container smoke. Health/readiness succeeded, private unauthenticated requests
were refused, the default website remained closed, the public component projection
was empty, and restart preserved pauses/database integrity. The temporary fixture
container and keys were removed. The formal service remains unpaired and stopped;
no fake production registration was generated and no gateway rule was changed.

The environment's PostgreSQL SSLRequest returned N. Verified-TLS probe acceptance
cannot pass against that listener as-is; do not disable TLS verification or alter
the shared PostgreSQL/Dify service as an incidental fix. A reviewed trusted TLS
path and read-only identity, plus real provider billing authorization, remain
operational gates. The candidate preparation does not publish a release, change
the market or claim S00–S11 completion. Complete CI passed at a4ffec6 before this
documentation-only update.


## Accessibility acceptance and unified-release hold (2026-10-23)

A pinned axe-core browser check first reproduced insufficient primary-button text
contrast (4.1:1 on the Portal light-blue theme) and a keyboard-inaccessible
horizontal table region. Primary buttons now select the higher-contrast black or
white text using sRGB luminance; invalid non-hex theme values fall back to the
accessible default. Table wrappers have a named, visibly focused keyboard stop
and column headers declare scope. No host page or sandbox permission changed.

Eight contract tests and seven browser scenarios pass. The added WCAG A/AA scan
covers narrow-screen light/dark private overview, component management/editor,
operations, and the independent public overview. This is automated evidence, not
a claim of complete manual screen-reader acceptance. Generated public assets
were rebuilt through the normal builder.

The owner explicitly deferred the Portal upgrade and asked to retain the Status
candidate for a unified release. The target's formal service stays stopped and
unpaired, with probes/publication paused and no gateway change. The existing
server candidate is a4ffec6; these later UI fixes remain in the PR until a new
candidate is verified. No dependency PR merge, release or Portal restart was
performed.


## PostgreSQL destination and end-to-end notification drills (2026-10-23)

Driver-source inspection found a real hostname incompatibility: pgx resolved the
configured hostname before calling the guarded dialer, which then refused the
resolved address because it no longer matched the configured host. A failing
binding test preceded the fix. PostgreSQL's driver lookup now preserves only the
configured hostname, leaving all DNS resolution, full-answer validation and pinned
IP dialing in the existing guard. Certificate identity still uses that original
hostname, TLS verification stays enabled and plaintext fallbacks stay absent.
No storage shape or feature configuration changed.

A real pgx SSL/extended-query fixture over in-memory sockets verifies the guarded
hostname can execute only SELECT 1. Additional cases refuse TLS-disabled peers,
untrusted roots and wrong certificate names before startup reaches the peer,
and bound stalled SSL negotiation, authentication and query work to the caller's
deadline. HTTP fixtures exercise bounded header/body waits, same-target redirect
refusal without forwarding credentials, and repeated DNS lookup with an initially
allowed address rebinding to a mixed metadata answer. No system DNS or external
database/provider is used by these fixtures.

An optional PORTAL_BINARY integration now drives a real isolated Portal process
and Status's independent reducer/outbox/publisher. It parses a low-balance fixture,
confirms the incident, loads the saved dedicated publisher credential, observes
source HTTP 429 cooldown, then loses a capture acknowledgement after Portal has
committed the event. The retry retains its occurrence/payload and obtains the
same event ID. Portal routes one signed channel delivery; a local receiver's 429
is retried after at least its seven-second Retry-After with the same event and
delivery IDs. Durable history records two attempts and one accepted delivery.
Payloads exclude the private financial amount/currency, account alias, label and
both model/publication credentials. All receivers and credentials are fixtures.

CI now pins the already-verified b23f43ce platform integration and runs this real
capture/channel drill before the browser suite. Full service race tests (including
the optional integration), vet, build and workflow lint passed locally. Full Apps
CI passed at 47824bb before these further changes. The deployment hold is
unchanged: no dependency merge, Portal upgrade, service activation or gateway edit.


The real-Portal and browser fixture launchers now discard inherited RP_* settings
before supplying their temporary configuration. Regression runs deliberately set
invalid caller DB/listen overrides: both harnesses failed before the isolation fix
and passed afterward. This prevents an operator's shell infrastructure overrides
from redirecting acceptance tests into a different database or listen address.
Seven browser workflows passed with those hostile fixture-only environment values.


A stricter stalled-peer variant exposed a second real driver interaction: query
cleanup could retain the wire asynchronously, and stalled authentication cleanup
could add roughly five seconds of TLS close-notify after a 100 ms probe deadline.
The connection now owns a cancellation scope from guarded dial through setup,
query and teardown. Every raw wire closes at the probe deadline, graceful cleanup
has a bounded child context, and late driver cleanup cannot open a new connection
after that scope ends. Tests prove authentication, query and stalled teardown
release the fixture peer within the configured probe budget. The earlier five-
second failure now completes at approximately 100 ms. No TLS verification or
private-address policy was relaxed.

Browser CI deliberately supplies invalid inherited database/listen overrides so
fixture isolation remains a regression gate rather than only a one-time check.
