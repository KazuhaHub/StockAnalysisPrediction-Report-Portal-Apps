# Status acceptance ledger

This ledger preserves the complete S00–S11 scope in
[the implementation plan](../../../docs/implementation-plan.md). A passing unit
or browser test is evidence for its own behavior, not a claim of full acceptance.

| Package | Current evidence | Remaining gate |
| --- | --- | --- |
| S00 | Repository/capability inventory and official adapter fixtures; authorized target inspection now verifies Portal v2026.43.2, Dify image 1.17.1, Docker Compose 5.3.0 and PostgreSQL without TLS | Verified PostgreSQL TLS path and read-only identity, provider account/site/authorization verification |
| S01 | Portal paired backend platform, migration 0008, identity/scopes/directory and negative tests; PR #142 CI passed at b23f43ce after main integration; local Go/PG/race/web/browser checks passed | Portal #141/#142 are merged; v2026.43.2 Beta is published and deployed; full main CI, isolated PG/released-binary upgrade, final backup, business-count and forecast-setting continuity, health and offline post-backup restore verified; remaining installed-app update acceptance |
| S02 | Public shared repo; approved independent schema; locking/key/backup/restore tests; CLI | Wrong-key/future-schema/missing-product/occupied-rollback rejection and live continuity now tested; released-version operator upgrade/rollback remains gated |
| S03 | Signed private API, explicit public DTOs, read/finance grants, filtered incident counts/detail; two-OU browser check | Component paging/search/count/detail/export authority and separate finance projection now tested; remaining broad account recreation/platform audit |
| S04 | Four workers, persisted leases, credential/target revision fences, read-only probes and signed heartbeat | Abandoned lease/restart evidence and manual saved-configuration controls now tested; Guarded PostgreSQL hostname/TLS negotiation, untrusted/mismatched certificate refusal, no plaintext fallback and TLS/auth/query/teardown timeout and wire-release drills now pass; HTTP header/body timeouts, same-target redirect refusal and subsequent DNS rebinding refusal now tested; actual target TLS/read-only identity acceptance remains |
| S05 | DeepSeek exact-decimal/currency fixtures, Qwen cash/credit distinction, ACS3 official vector, pinned endpoints | Unsupported capability and setup hints tested; Shared-account references and cross-component/currency guards tested; remaining deployment-specific non-production billing authorization |
| S06 | Confirmation/hysteresis reducer, incident transitions, maintenance and hourly aggregates | Partial-hour and missing/paused-time accounting plus both history charts tested; Retrospective full-hour corrections, expired-evidence fallback, multi-bucket evidence and retention boundary now tested; Configurable bounded retention and public paging tested; remaining broader failure-drill audit |
| S07 | Atomic immutable outbox, namespace preflight, same-occurrence retries, publisher revision fences and queue review | Two-component/two-OU inbox routing, duplicate/changed-content checks, restart lease retry, uncertain restore/discard and storm suppression now tested; Real isolated Portal capture-to-signed-WebHook drill now covers source quota cooldown, lost capture acknowledgement/deduplication, channel Retry-After, stable delivery IDs and financial redaction; real SMTP/Slack/operator acceptance remains |
| S08 | Three-locale sandbox ZIP; admin component/monitor/grant/credential/operations UI; browser multi-monitor save | Form-error input retention/focus, duplicate-action guard, operations bridge budget, dark theme, locale switching and keyboard navigation tested; Component detail/export and visible idle polling added; Runtime capability refusal/retry and paused first-start now tested; Automated WCAG A/AA checks now cover light/dark mobile overview, component list/editor, operations and public overview; primary contrast and keyboard table scrolling fixed; remaining manual screen-reader/zoom audit |
| S09 | Private redirect and exact public proxy templates; real browser prefix/public-isolation check | Real nginx allowlist/assets/history passed CI at 05787ac; bounded peer/global rate budgets and forwarded-header bypass tests now pass; production capacity remains deployment-specific |
| S10 | Deterministic local ZIP/checksum and pure-Go service archive builder; executable/version/checksum/repeated-byte verification; six-target CI added; service Dockerfile/compose | All six artifact target jobs passed at 8d580d9; complete CI passed at 47824bb; independent Linux candidate installed and isolated container restart/default-access smoke passed on the target host; A guarded manual publication workflow now verifies exact-main CI, six archives, released-Portal integration, prebuilt image bytes, immutable asset download and acceptance records; its live publication, migration/index compatibility and operator upgrade/rollback remain gated |
| S11 | Local Go race/vet/build/vulnerability checks; CLI storage tests; eight frontend contract tests; seven real browser scenarios plus the isolated Portal/channel failure drill | Full requirement-by-requirement audit, remaining failure drills and operator sign-off; first complete CI run passed at 636db6f |

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
