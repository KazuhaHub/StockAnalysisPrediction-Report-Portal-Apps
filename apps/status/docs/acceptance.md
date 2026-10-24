# Status acceptance ledger

This ledger preserves the complete S00–S11 scope in
[the implementation plan](../../../docs/implementation-plan.md). A passing unit
or browser test is evidence for its own behavior, not a claim of full acceptance.

## Target PostgreSQL checks, 2026-10-23 Pacific

Prepared an independent PostgreSQL-aware stunnel TLS gateway, private CA and
dedicated probe login. The original PostgreSQL SSL setting remains off. The
explicit final hop is private same-host TCP; certificate verification protects the
Status-to-gateway connection. The deployment and rollback boundaries are in
[the target runbook](postgresql-target-deployment.md).

The new role has CONNECT only and no existing business table/schema/sequence or
custom security-definer access. An authentication block permits only this login
from the fixed gateway address to the target database, rejecting its other sources
and databases. Existing authentication rules were byte-preserved and backed up;
the edited file parsed without errors before reload. No business schema changed.

The actual `status.Prober.Check` from clean source
`d529abc4fc30d6e4df2c650a6255052b4a0854af`, compiled as an isolated one-shot harness,
ran in candidate runtime image
`sha256:a99326edc3d3dd3b9782b1b5011dd5ad23caa6fbb58edb131aca7344b1e3bbdf`
as UID 1001 with a read-only filesystem, dropped capabilities and bounded resources.
At `2026-10-24T03:54:49Z`, the verified-TLS query returned success/reachable and
`read_query_only` in 22 ms. Wrong password and untrusted CA returned failure.
Current gateway controls also reject a wrong hostname and plaintext StartupMessage.
Another database is refused, and an actual gateway restart is followed by another
successful guarded SELECT 1 at `03:57:50Z` (16 ms). Portal health stays DB/OK.

Receipts, source/executable hashes, private configuration and protected rollback
material live under `/data/report-portal/status-postgres/`. Credentials passed only
through stdin/file mounts and are absent from receipts. The candidate trust bundle
preserves public CA roots; its prepared override was resolved without starting the
formal service. Formal Status remains stopped/unpaired/paused, with no monitored
component or public gateway enabled by these checks. This proves the real database
path and adapter controls, not marketplace installation or continuous production
observation. Qwen billing, final operator policy and immutable distribution remain.

Portal PR #172 corrected incomplete historical test fixtures and their selective
replay assertion, without changing runtime migrations or rewriting any production
ledger. It merged as `5c3344cf43c6326fd5ef95f760264ce8f8d5e58d`; full exact-main CI
`40059777948`, including all race shards, passed.

Protected infrastructure backup
`/data/report-portal/backups/status-postgres-20261024T040425Z/infrastructure.tgz`
was extracted into an isolated owner-only scratch directory. All sixteen named
files matched their source hashes and the restored leaf verified against its CA;
scratch copies were removed. This proves file/chain recovery, not a live database
or automatic role/pairing restore. An off-host recovery copy remains an operator
storage responsibility, not a claimed same-host disaster-recovery guarantee.

## Target read-only provider checks, 2026-10-23 Pacific

After the owner explicitly identified Dify as the credential source, inspected
provider credential field names and matching workflow environment-variable names
in the target's single workspace through a read-only transaction. DeepSeek uses
the official `api.deepseek.com` endpoint. Tongyi has `dashscope_api_key` and
`use_international_endpoint`; no RAM AccessKey pair was found in those sources.
The model invocation key was not submitted to a billing endpoint.

An isolated one-shot executable imported the actual `status.Prober.Check` from
clean source `d0916654896ed8f8f839027322ae2ad9def139f7` and accepted its inputs only
on stdin. The Dify process decrypted the existing DeepSeek key using its own key
provider and passed it in memory. It selected a scoped token for the current
CoD-V3.17 report workflow. Neither credential was printed, copied into Status
storage, placed in process arguments or committed. No workflow/inference ran.

At `2026-10-24T03:23:03Z`, the actual guarded adapters returned:

| Check | Outcome | Reason | Capability | Duration |
| --- | --- | --- | --- | --- |
| DeepSeek account balance | success | balance_read | account_balance; one balance record | 196 ms |
| Dify report workflow GET /v1/info | success | reachable | read_access_only | 62 ms |

The receipt intentionally excludes amounts, currencies, account references and
credentials. Source, executable, receipt and verified SHA256SUMS are retained in
the protected target directory
`/data/report-portal/status-candidate-f06279d/acceptance/`. The temporary executable
was removed from the Dify container after the check. Formal Status remains stopped,
unpaired and paused. This proves these two real read-only calls, not scheduled
production observation, notification delivery, public activation or installed UI.

Qwen account billing still requires an account owner's RAM identity; the reviewed
minimal policy and exact operator steps are in the operator guide. PostgreSQL
acceptance was pending at this checkpoint and was subsequently verified above.
Final manual/operator acceptance, immutable Status publication and marketplace
installation remain incomplete.

Marketplace preparation at `d091665` passed both full twelve-job CI runs
`40057064497` and `40057068779`, including thirty Python tests, thirteen browser
scenarios and the existing demo's real public download. Portal PR #171 separately
binds reviewed market declarations to the downloaded manifest; exact-source test
CI `40057523290` and CodeQL `40057521307` passed, and it merged as
`493a5c3d3e6813043437de939f1370717f597628`. It is not yet deployed. The default
catalogue and current installed apps were not changed by that merge.

| Package | Current evidence | Remaining gate |
| --- | --- | --- |
| S00 | Repository/capability inventory; Portal v2026.43.2, Dify 1.17.1 and Compose 5.3.0 inspected; native PostgreSQL SSL is off and a dedicated private TLS gateway/read-only identity is now verified | Qwen billing account/site/authorization verification; owner will provision the RAM credential |
| S01 | Portal paired backend platform, migration 0008, identity/scopes/directory and negative tests; PR #142 CI passed at b23f43ce after main integration; local Go/PG/race/web/browser checks passed | Portal #141/#142 are merged; v2026.43.2 Beta is published and deployed; full main CI, isolated PG/released-binary upgrade, final backup, business-count and forecast-setting continuity, health and offline post-backup restore verified; installed-app disable/reinstall/uninstall and fresh-unpaired behavior now pass against the released Portal; production install/pairing and released-version rollout remain |
| S02 | Public shared repo; approved independent schema; locking/key/backup/restore tests; CLI | Wrong-key/future-schema/missing-product/occupied-rollback rejection and live continuity now tested; released-version operator upgrade/rollback remains gated |
| S03 | Signed private API, explicit public DTOs, read/finance grants, filtered incident counts/detail; two-OU browser check | Component paging/search/count/detail/export authority and separate finance projection now tested; real released-Portal account deletion/recreation now proves changed opaque principal, rejected old application token, no inherited direct grant and nondisclosing hidden detail; final release/production authority review remains |
| S04 | Four workers, persisted leases, revision fences, read-only probes and signed heartbeat; actual target PostgreSQL verified-TLS SELECT 1, scoped login and restart/negative controls pass | Abandoned lease/restart and saved-configuration controls tested; guarded hostname/TLS, untrusted/mismatched certificate refusal, no plaintext fallback, setup/query/teardown deadlines and wire release pass; HTTP timeout, redirect and rebinding controls pass; continuous production observation awaits market installation/pairing |
| S05 | DeepSeek exact-decimal/currency fixtures, Qwen cash/credit distinction, ACS3 official vector, pinned endpoints | Unsupported capability and setup hints tested; Shared-account references and cross-component/currency guards tested; remaining deployment-specific non-production billing authorization |
| S06 | Confirmation/hysteresis reducer, incident transitions, maintenance and hourly aggregates | Partial-hour and missing/paused-time accounting plus both history charts tested; Retrospective full-hour corrections, expired-evidence fallback, multi-bucket evidence and retention boundary now tested; Configurable bounded retention and public paging tested; named offline failure drills are mapped in requirement-audit.md, including TTL boundary/private-public expiry; live target/operator acceptance remains |
| S07 | Atomic immutable outbox, namespace preflight, same-occurrence retries, publisher revision fences and queue review | Two-component/two-OU inbox routing, duplicate/changed-content checks, restart lease retry, uncertain restore/discard and storm suppression now tested; Real isolated Portal capture-to-signed-WebHook drill now covers source quota cooldown, lost capture acknowledgement/deduplication, channel Retry-After, stable delivery IDs and financial redaction; real SMTP/Slack/operator acceptance remains |
| S08 | Three-locale sandbox ZIP; admin component/monitor/grant/credential/operations UI; browser multi-monitor save | Form-error input retention/focus, duplicate-action guard, operations bridge budget, dark theme, locale switching and keyboard navigation tested; Component detail/export and visible idle polling added; Runtime capability refusal/retry and paused first-start now tested; Automated WCAG A/AA checks now cover light/dark mobile overview, component list/editor, operations and public overview; primary contrast and keyboard table scrolling fixed; 320-CSS-pixel reflow with doubled app text, long labels and keyboard Enter/Tab/Space now tested in private overview/list/editor/operations and the public page; intrinsic field sizing fixed without weakening CSP; remaining manual screen-reader/native-browser-zoom audit |
| S09 | Private redirect and exact public proxy templates; real browser prefix/public-isolation check | Real nginx allowlist/assets/history passed CI at 05787ac; bounded peer/global rate budgets and forwarded-header bypass tests now pass; production capacity remains deployment-specific |
| S10 | Deterministic local ZIP/checksum and pure-Go service archive builder; executable/version/checksum/repeated-byte verification; six-target CI added; service Dockerfile/compose | All six artifact target jobs passed at 8d580d9; complete CI passed at 47824bb; independent Linux candidate installed and isolated container restart/default-access smoke passed on the target host; A guarded manual publication workflow now verifies exact-main CI, six archives, released-Portal integration, prebuilt image bytes, immutable asset download and acceptance records; its live publication, migration/index compatibility and operator upgrade/rollback remain gated |
| S11 | Local Go race/vet/build/vulnerability checks; CLI storage tests; eight frontend contract tests; thirteen real browser scenarios plus the isolated Portal/channel failure drill | Pre-release requirement audit is recorded in requirement-audit.md; actual environment, final manual/operator acceptance and release/catalogue rollout remain; first complete CI run passed at 636db6f |

Publication tooling now has sixteen focused policy tests (twenty-five Python
checks in total), including source/CI admission, hostile artifacts, metadata
binding, duplicate public assets and fail-closed draft handling. Local actionlint,
eight frontend contract tests, the real Portal/channel race drill and all seven
browser/accessibility scenarios pass against the checksum-verified **published
v2026.43.2 binary**, with inherited infrastructure overrides deliberately poisoned.
The first release-binary browser run exposed Portal's ordinary first-use release
notes blocking fixture clicks; fixture accounts now record prior release use
through the normal API before browser acceptance. The app does not suppress or
modify that production behavior. Browser packaging resolves the current manifest
version instead of hard-coding the development directory. Main CI now downloads
and verifies v2026.43.2 rather than compiling an unreleased platform branch.

No released app or completed production deployment is claimed. A private candidate
image, paused independent store and verified initial backup/restore are prepared
on the authorized target. The formal service is not started or paired; no gateway
route was changed. A temporary fixture container passed health, readiness,
unauthenticated private denial, closed website, empty public projection and
restart/pause checks, then was removed. Keep the default Portal
market and deployment overrides unchanged until the release artifacts and this
ledger's remaining gates have been verified.


Unified-release authorization, 2026-10-23: after forecast completion, the
owner authorized merging and releasing Portal. That supersedes the earlier hold.
Portal #141/#142 are merged and v2026.43.2 is deployed healthy on the target.
The protected deployment evidence records an isolated old-image PostgreSQL restore,
0007/0008 upgrade rehearsal, published-image verification, stopped-writer final
backup, prepared clean rollback target, production migrations, unchanged business
counts and forecast settings, and offline post-upgrade backup restore. Public SPA
and all 65 referenced assets returned successfully. The current verified native candidate is 720b1bc, staged separately on the target
from its successful CI artifact. Its image executable matches that artifact. The
stopped old database/key were copied, backed up and restored with integrity and
operating-pause checks. A non-root/read-only internal-network container passed
startup/restart, health/readiness, private 401, closed website and empty public
projection checks, then its fixture pairing/container/network were removed. The
a4ffec6 candidate is retained for recovery; do not use its older ZIP or binary.
No Status release, gateway, provider validation or marketplace rollout is inferred
from the completed Portal upgrade.

An existing production browser administrator session was confirmed without a new
account or credential reset. The application management page shows no installed
apps. Automatic upload of the verified candidate ZIP was stopped before preview
or installation because the browser extension lacks local file-URL access. No
extension permission, app permission or backend registration was changed. The
actual upload/install confirmation is pending; the formal candidate remains
stopped, paused and unpaired. This does not block independent remaining audits.

## Reflow and identity lifecycle follow-up

The narrow-layout test first reproduced document overflow after doubling text:
a 294-CSS-pixel private frame scrolled to 367 pixels. Intrinsic input/grid/fieldset
sizes caused the overflow. Shared private/public CSS now constrains those intrinsic
sizes and wraps long labels while retaining table-local scrolling and visible
focus. Nine browser scenarios pass against published Portal v2026.43.2, including
320-pixel layouts, doubled app text, 120-character labels, component/monitor forms,
operations and Enter/Tab/Space behavior. Public text enlargement is applied through
the same-origin stylesheet in the test fixture; the production CSP remains intact.
This is an enlarged-text/reflow test, not a claim of native zoom or screen-reader
acceptance. The earlier 720b1bc server/ZIP candidate predates this CSS fix.

A released-platform lifecycle test creates an explicitly user-granted component,
deletes and recreates its account, and verifies a different opaque principal,
403 for the old app token, no inherited component in list results and 404 without
the hidden label for detail. This complements the existing dual-driver Portal
identity-generation tests and current-OU browser checks. It runs only in isolated
fixture databases and does not create or delete production accounts.

## Independent-process and installation lifecycle drills

The complete browser suite now has thirteen scenarios against the published
Portal binary. The browser-close drill holds a real HTTP probe across context
closure, then observes another queued background check with no browser open.
Status outage is an actual service process stop: Portal authentication, report
reads and queue stay available, and the app recovers after service restart.
The inverse drill keeps Portal stopped for a complete later scheduled interval;
Status completes fresh observations and serves only the approved public DTO.

The lifecycle drill disables the backend, verifies token denial, reenables it,
reinstalls the ZIP and verifies cleared keys/new instance, then uninstalls it and
verifies registration/asset removal. A fresh unpaired installation displays no
component data or management controls. Portal's normal read/auth/queue APIs and
the independent service remain available. The local fixture is removed afterward;
none of these tests changes production installation or stops production services.

## Canonical marketplace installation acceptance

All fourteen browser scenarios passed against published Portal v2026.43.2. The
additional scenario fetches the actual shared repository's public catalogue and
immutable demo ZIP, previews its query permission, cancels without an installation
request, then explicitly confirms installation. It checks the installed scopes
and a real sandbox bridge query in the demo frame. This uses a disposable local
Portal database and removes the demo afterward. It neither installs Status through
the market nor grants production permissions. The earlier development-upload
observation is historical; a manual ZIP upload is not required for formal rollout.

The legacy catalogue exporter has four additional tests (34 shared Python tests
total). They cover canonical metadata with preserved selection/path/archive bytes,
refusal of changed bytes and path escape, unsupported capabilities and symlinked
archives. The canonical catalogue's real download verification also passed. Its
single published entry remains the demo; Status publication gates remain open.

The same fourteen scenarios subsequently passed against published Portal
v2026.43.3 and v2026.43.4. The target is now on v2026.43.4 with the canonical
compiled market default, preserved saved settings/data, old/new image restore
checks and healthy public assets. See [the host rollout evidence](portal-market-rollout.md)
for exact source, CI, image and protected receipt references. This supersedes
earlier host-version and default-market pending observations without claiming
Status publication, installation or activation.

Unit evidence now explicitly covers zero/negative fractional/large balances for
both provider families, typed authentication/permission failures without balances,
and private/public last-success expiry at and immediately after TTL without
rewriting evidence time. The [requirement audit](requirement-audit.md) separates
this verified fixture scope from the unfinished environment/publication gates.

## Explicit local PostgreSQL transport

The local socket configuration test first rejected the new transport; frontend
contract tests also reproduced the missing capability gate and setup hint.
The implementation now selects Unix sockets explicitly, with no configurable
arbitrary path and no network fallback. Actual Unix protocol fixtures pass for
SELECT 1, authentication/query deadlines, destination refusal, symlink/file
replacement and stale socket failure. The existing verified-network TLS suite
continues to pass. Complete Go race tests, vet, eight frontend contract tests and
34 shared Python tests passed locally.

Fifteen browser scenarios pass against published Portal v2026.43.4. The new case
saves/reopens a PostgreSQL local monitor and proves switching back from TLS does
not retain host/CIDR destinations. It also exposed select labels polluted by
option text; selects now have explicit localized accessible names. Subsequent
target acceptance verified the scoped local SCRAM rule, actual SELECT 1 and
wrong-password/database/port controls, as described in
[the local socket runbook](postgresql-local-socket.md). No gateway was recreated
and no production Status process, monitor or notification was enabled.
