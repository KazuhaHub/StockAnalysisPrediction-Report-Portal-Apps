# Status acceptance ledger

This ledger preserves the complete S00–S11 scope in
[the implementation plan](../../../docs/implementation-plan.md). A passing unit
or browser test is evidence for its own behavior, not a claim of full acceptance.

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
verified TLS/read-only identity, final manual/operator acceptance, immutable Status
publication and marketplace installation remain incomplete.

Marketplace preparation at `d091665` passed both full twelve-job CI runs
`40057064497` and `40057068779`, including thirty Python tests, thirteen browser
scenarios and the existing demo's real public download. Portal PR #171 separately
binds reviewed market declarations to the downloaded manifest; exact-source test
CI `40057523290` and CodeQL `40057521307` passed, and it merged as
`493a5c3d3e6813043437de939f1370717f597628`. It is not yet deployed. The default
catalogue and current installed apps were not changed by that merge.

| Package | Current evidence | Remaining gate |
| --- | --- | --- |
| S00 | Repository/capability inventory and official adapter fixtures; authorized target inspection now verifies Portal v2026.43.2, Dify image 1.17.1, Docker Compose 5.3.0 and PostgreSQL without TLS | Verified PostgreSQL TLS path and read-only identity, provider account/site/authorization verification |
| S01 | Portal paired backend platform, migration 0008, identity/scopes/directory and negative tests; PR #142 CI passed at b23f43ce after main integration; local Go/PG/race/web/browser checks passed | Portal #141/#142 are merged; v2026.43.2 Beta is published and deployed; full main CI, isolated PG/released-binary upgrade, final backup, business-count and forecast-setting continuity, health and offline post-backup restore verified; installed-app disable/reinstall/uninstall and fresh-unpaired behavior now pass against the released Portal; production install/pairing and released-version rollout remain |
| S02 | Public shared repo; approved independent schema; locking/key/backup/restore tests; CLI | Wrong-key/future-schema/missing-product/occupied-rollback rejection and live continuity now tested; released-version operator upgrade/rollback remains gated |
| S03 | Signed private API, explicit public DTOs, read/finance grants, filtered incident counts/detail; two-OU browser check | Component paging/search/count/detail/export authority and separate finance projection now tested; real released-Portal account deletion/recreation now proves changed opaque principal, rejected old application token, no inherited direct grant and nondisclosing hidden detail; final release/production authority review remains |
| S04 | Four workers, persisted leases, credential/target revision fences, read-only probes and signed heartbeat | Abandoned lease/restart evidence and manual saved-configuration controls now tested; Guarded PostgreSQL hostname/TLS negotiation, untrusted/mismatched certificate refusal, no plaintext fallback and TLS/auth/query/teardown timeout and wire-release drills now pass; HTTP header/body timeouts, same-target redirect refusal and subsequent DNS rebinding refusal now tested; actual target TLS/read-only identity acceptance remains |
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

Unit evidence now explicitly covers zero/negative fractional/large balances for
both provider families, typed authentication/permission failures without balances,
and private/public last-success expiry at and immediately after TTL without
rewriting evidence time. The [requirement audit](requirement-audit.md) separates
this verified fixture scope from the unfinished environment/publication gates.
