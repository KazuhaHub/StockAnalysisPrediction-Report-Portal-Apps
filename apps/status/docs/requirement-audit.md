# Status pre-release requirement audit

This audit follows the original [S00-S11 plan](../../../docs/implementation-plan.md).
It does not redefine completion around passing development checks. Local fixture
evidence proves the named behavior, not production configuration or provider access.
The [acceptance ledger](acceptance.md) records current source and deployment state.

For the initial Beta, the owner's 2026-10-24 install-first decision is recorded in
[release readiness](../../../docs/status-0.1.0-beta.2-readiness.md). Optional live
credentials and recipients are configured after installation. The matrix below
preserves the larger plan and its historical observations rather than presenting
those optional configuration tasks as distribution blockers.

## Current-state supplement

The [Beta.3 production rollout](react-ui-production-rollout.md) records the actual
React/Ant Design market update, re-pairing and continuity of four monitors, three
sealed credentials and their existing history. It supersedes the older UI/version
checkpoint while retaining the explicit limits on optional configuration below.

The [production rollout audit](production-rollout.md) records successful immutable
publication, canonical listing, actual installation/private pairing, native Chrome
reads, authenticated `/status`, independent-service restart and isolated backup
verification. It supersedes the pending distribution/deployment statements in the
historical matrix below. The matrix retains its original scope and fixture limits;
it must not be read as a claim that optional production credentials, real recipient
delivery or full manual accessibility certification have been completed.

## Historical pre-publication matrix

## Product and authorization boundaries

| Requirement | Inspected evidence | Classification and limit |
| --- | --- | --- |
| Independent service, ZIP and shared repository | `cmd/status`, frontend package builder, shared protocol package, Apps repository and artifact CI | Implemented; immutable Status publication remains pending |
| No run-analysis or queue modification | Status sources stay in the Apps repository; Portal prerequisite is generic; browser outage and uninstall cases read Portal home/auth/queue successfully | Verified in isolated integration; no paid analysis is submitted by the tests |
| Continuous observation independent of the browser | Browser-close scenario holds an actual HTTP probe, closes the browser, completes it, then queues and observes a second background check | Verified against the published Portal and separate service process |
| Current OU authority and default administrator-only components | Disjoint-OU/membership-change browser cases; `componentFilter`, current viewer identity and principal directory | Automated evidence covers reads; actual production grants still need configuration |
| Account deletion/recreation and old token denial | Recreated-account browser scenario; dual-driver Portal identity-generation tests | Old token returns 403; new opaque principal cannot inherit a direct grant; hidden detail returns 404 |
| Separate exact-balance access | `TestFinanceRequiresSeparateGrant`, export/current-finance tests, public DTOs | Automated verification; no real account balance has been asserted |
| Request/boot binding, revocation and negative boundaries | Shared assertion/handshake/policy tests; Portal proxy and lifecycle tests | Signature, method/path/body, issuer/audience/app/instance, expiry, replay, current boot and current authority are enforced |
| No plaintext saved secrets in read/export/public data | Credential sealing and identity/kind binding tests; export tests; real notification redaction drill | Verified for tested DTOs; production secret provisioning is pending |

## Required failure drills

| Named failure | Evidence | Result and scope |
| --- | --- | --- |
| Status unavailable | Actual service process stop/restart in the browser suite | App refuses data; Portal authentication, report reads and queue remain available; refresh recovers after service restart |
| Portal unavailable | Actual Portal process stop while the independent HTTP observer runs | Status completes the in-flight check and a later scheduled interval while Portal remains stopped; readiness and approved public reads remain available |
| Provider quota API unavailable | `TestBalanceObservationFailureRemainsUnknown`, provider Retry-After tests | DeepSeek/Qwen network failure yields unknown without a fabricated balance; cooldown prevents premature next observation |
| Negative/zero credit | `TestNonpositiveProviderBalancesNeverBecomeHealthy`, exact-decimal adapter tests | Zero, negative fractional and large negative amounts remain exact and non-healthy; a positive credit line does not imply available funds |
| Expired/unauthorized key | `TestBillingAuthenticationFailureRemainsUnknown`, Qwen permission/site fixtures | Both provider families return unknown with their typed setup/authentication reason and no inferred zero balance |
| Database timeout | `TestPostgresGuardedDriverTLSAndTimeouts`; real target adapter checks in acceptance ledger | Wire fixtures cover deadlines/socket release; real verified-TLS SELECT 1 succeeds, wrong password/CA/hostname and another database are refused, and gateway restart recovers |
| Last-success evidence becomes stale | `TestLastSuccessExpiresInPrivateAndPublicSnapshotsWithoutRewritingItsTime` | Private/public snapshots retain original evidence times, change to stale/unknown after TTL and do not invent a new success |
| Removed OU membership | Current-OU browser and component/export authority tests | Counts, list, detail, export and inbox access re-evaluate current authority |
| Service restart mid-probe | `TestExpiredProbeAfterRestartRecordsUnknownAndRequiresFreshConfirmation`, revision/lease tests | Abandoned evidence is unknown; old configuration/credential results cannot commit; fresh confirmation is required |
| Outbox response loss | `TestPortalNotificationCaptureAndChannelQuota` | Real Portal durably captures before the acknowledgement is withheld; retry keeps occurrence/event identity and does not duplicate accepted work |
| Restore after possible delivery | `TestRestoreUncertainPublicationRequiresExplicitDiscard`, queue fingerprint and storage recovery tests | Uncertain work requires review; restored probes/publication remain paused and changed snapshots cannot be resumed blindly |
| Incorrect public projection | Public DTO, paging/history tests; browser prefix checks; real nginx allowlist smoke | Global/component approval is required; private labels/configuration, balances and OU details stay excluded; private API routes are not gateway-published |

These are isolated fixtures. They do not authorize or prove delivery to a real
Email/Slack recipient, real billing authorization, or a production outage exercise.

## UI, lifecycle and recovery

| Requirement | Evidence | Classification and limit |
| --- | --- | --- |
| Self-contained installable ZIP, existing preview/parser and sandbox bridge | Real Portal installer and null-origin iframe browser suite; frontend bridge contracts | Verified with development artifacts; production install confirmation is pending |
| Fresh install without a backend fails safely | Lifecycle scenario uninstalls, installs a fresh ZIP without a registration and opens the app | Data and management controls stay unavailable; a deliberate pairing is required |
| Disable, reinstall and uninstall revoke access | Lifecycle browser scenario plus dual-driver Portal connection tests | Disabled/stale tokens are denied; reinstall clears keys/changes instance; uninstall removes registration/assets |
| App uninstall does not silently own the separate process | Lifecycle scenario observes service readiness after uninstall | Verified; operator must separately stop probes/service and revoke publication credentials as documented |
| Keyboard, contrast, labels, mobile/desktop, themes and locales | Contract tests and automated WCAG A/AA scans; keyboard/language/theme scenarios | Tested scope is explicit; no claim of complete assistive-technology certification |
| Narrow layout and enlarged text | 320-CSS-pixel, doubled-text, long-label private/public scenario | Regression reproduced and fixed; tests preserve public CSP and exercise Enter/Tab/Space. Native browser zoom and manual screen-reader review remain unverified |
| History, retention and coverage | Partial-hour, paused/maintenance, missing-evidence, multi-bucket and retention-boundary tests | No observations/history before creation or fabricated healthy coverage; bounded settings and cleanup preserve pending evidence |
| Independent backup/restore and rejection preserve live data | Key/schema/product/rollback rejection tests; verified host candidate backup and isolated restore | Fixture/host preparation verified; a released-version production app upgrade/rollback remains pending |
| Private `/status` and optional public prefix | Private redirect/public exact-allowlist templates; browser/nginx prefix tests | Implementation verified; actual deployment gateway mode/rule is not activated |

## Distribution and environment exit gates

| Gate | Authoritative current evidence | Remaining work |
| --- | --- | --- |
| Notification and generic platform prerequisites | Portal #141/#142 and protocol #1 merged; minimum v2026.43.2 published; target now runs v2026.43.4 with [recovery and continuity evidence](portal-market-rollout.md) | Complete actual installed-app pairing/configuration review |
| Dify, PostgreSQL and both provider families | Guarded Dify info and DeepSeek balance succeeded; the removed gateway is replaced by [actual Unix socket SELECT 1 and negative controls](postgresql-local-socket.md), with no added service or native SSL change | Complete Qwen billing account/site/authorization checks after owner-provisioned RAM credentials, then configure and verify the paired service; Dify holds a DashScope model key |
| Six platforms and exact image executable bytes | Artifact builder and CI; non-root prebuilt image checks | Publish a non-development app-qualified version from clean reviewed main after acceptance |
| Released minimum Portal compatibility | CI uses checksum-verified published v2026.43.2; all fourteen browser scenarios also pass locally against published v2026.43.3 and v2026.43.4 | Record the final Status version-specific acceptance and operator evidence |
| Immutable tag/image/assets and public downloads | Guarded workflow, policy tests, metadata binding and draft/public download verification implementation | No actual Status release has run; do not treat workflow code as publication evidence |
| Canonical catalogue and legacy-compatible migration | Apps #4 exporter/real market acceptance merged and CI passed; Portal #171 declaration binding and #174 default migration are deployed in v2026.43.4; legacy URLs and saved overrides are preserved | Add Status only after its immutable artifacts exist and are verified; complete its actual market installation |
| Production operator approval and activation | Current candidate is prepared, paused, stopped and unpaired; existing admin browser session is available | Marketplace installation/permission confirmation after publication; private pairing; target configuration; deliberate probe/audience/gateway review; a manual ZIP is optional controlled acceptance |

Overall completion is **not proven**. In particular, the production app, actual
Qwen billing authorization, final operator/manual
acceptance, immutable Status publication and its catalogue/installation rollout are not
substituted by the successful fixture tests above.
