# Status acceptance ledger

This ledger preserves the complete S00–S11 scope in
[the implementation plan](../../../docs/implementation-plan.md). A passing unit
or browser test is evidence for its own behavior, not a claim of full acceptance.

| Package | Current evidence | Remaining gate |
| --- | --- | --- |
| S00 | Repository/capability inventory and official adapter fixtures; authorized target inspection found Portal v2026.43, Dify image 1.17.1, Docker Compose 5.3.0 and PostgreSQL without TLS | Compatible Portal deployment, verified PostgreSQL TLS path and read-only identity, provider account/site/authorization verification |
| S01 | Portal paired backend platform, migration 0008, identity/scopes/directory and negative tests; PR #142 CI passed at c4402084; latest main integration 2e5375ed passed local Go/PG/race/web/browser checks | Final platform update checks and review/merge after notification dependency |
| S02 | Public shared repo; approved independent schema; locking/key/backup/restore tests; CLI | Wrong-key/future-schema/missing-product/occupied-rollback rejection and live continuity now tested; released-version operator upgrade/rollback remains gated |
| S03 | Signed private API, explicit public DTOs, read/finance grants, filtered incident counts/detail; two-OU browser check | Component paging/search/count/detail/export authority and separate finance projection now tested; remaining broad account recreation/platform audit |
| S04 | Four workers, persisted leases, credential/target revision fences, read-only probes and signed heartbeat | Abandoned lease/restart evidence and manual saved-configuration controls now tested; remaining timeout/rebinding/private-policy deployment acceptance |
| S05 | DeepSeek exact-decimal/currency fixtures, Qwen cash/credit distinction, ACS3 official vector, pinned endpoints | Unsupported capability and setup hints tested; Shared-account references and cross-component/currency guards tested; remaining deployment-specific non-production billing authorization |
| S06 | Confirmation/hysteresis reducer, incident transitions, maintenance and hourly aggregates | Partial-hour and missing/paused-time accounting plus both history charts tested; Retrospective full-hour corrections, expired-evidence fallback, multi-bucket evidence and retention boundary now tested; Configurable bounded retention and public paging tested; remaining broader failure-drill audit |
| S07 | Atomic immutable outbox, namespace preflight, same-occurrence retries, publisher revision fences and queue review | Two-component/two-OU inbox routing, duplicate/changed-content checks, restart lease retry, uncertain restore/discard and storm suppression now tested; remaining full sender-to-channel timeout/quota drill |
| S08 | Three-locale sandbox ZIP; admin component/monitor/grant/credential/operations UI; browser multi-monitor save | Form-error input retention/focus, duplicate-action guard, operations bridge budget, dark theme, locale switching and keyboard navigation tested; Component detail/export and visible idle polling added; Runtime capability refusal/retry and paused first-start now tested; Automated WCAG A/AA checks now cover light/dark mobile overview, component list/editor, operations and public overview; primary contrast and keyboard table scrolling fixed; remaining manual screen-reader/zoom audit |
| S09 | Private redirect and exact public proxy templates; real browser prefix/public-isolation check | Real nginx allowlist/assets/history passed CI at 05787ac; bounded peer/global rate budgets and forwarded-header bypass tests now pass; production capacity remains deployment-specific |
| S10 | Deterministic local ZIP/checksum and pure-Go service archive builder; executable/version/checksum/repeated-byte verification; six-target CI added; service Dockerfile/compose | All six artifact target jobs passed at 8d580d9; complete CI passed at a4ffec6; independent Linux candidate installed and isolated container restart/default-access smoke passed on the target host; immutable app release, migration/index compatibility and operator upgrade/rollback remain gated |
| S11 | Local Go race/vet/build/vulnerability checks; CLI storage tests; frontend contract tests; six real browser scenarios | Full requirement-by-requirement audit, remaining failure drills and operator sign-off; first complete CI run passed at 636db6f |

No released app or completed production deployment is claimed. A private candidate
image, paused independent store and verified initial backup/restore are prepared
on the authorized target. The formal service is not started or paired; no gateway
route was changed. A temporary fixture container passed health, readiness,
unauthenticated private denial, closed website, empty public projection and
restart/pause checks, then was removed. Keep the default Portal
market and deployment overrides unchanged until the release artifacts and this
ledger's remaining gates have been verified.


Deployment hold, 2026-10-23: the owner chose to leave the current Portal release
running and retain the Status candidate until the unified release. Do not upgrade
Portal, merge deployment dependencies as a deployment shortcut, start/pair the
formal Status instance or change the gateway for this preparation. The candidate
on the target remains a4ffec6; later source/ZIP fixes belong to the reviewed PR
and require a new verified candidate before activation.
