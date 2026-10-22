# Status acceptance ledger

This ledger preserves the complete S00–S11 scope in
[the implementation plan](../../../docs/implementation-plan.md). A passing unit
or browser test is evidence for its own behavior, not a claim of full acceptance.

| Package | Current evidence | Remaining gate |
| --- | --- | --- |
| S00 | Repository and capability inventory; official Dify/DeepSeek/Alibaba documents and adapter fixtures | Deployment-specific versions, account/site/authorization capability verification |
| S01 | Portal paired backend platform, migration 0008, identity/scopes/directory and negative tests; PR #142 CI passed at 55db11f5 | Final platform update checks and review/merge after notification dependency |
| S02 | Public shared repo; approved independent schema; locking/key/backup/restore tests; CLI | Broader upgrade/rollback failure drills (non-root image readiness and offline backup/restore passed CI) |
| S03 | Signed private API, explicit public DTOs, read/finance grants, filtered incident counts/detail; two-OU browser check | Broader pagination/detail/export audit; publication-gated coarse history and private-label isolation now tested |
| S04 | Four workers, persisted leases, credential/target revision fences, read-only probes and signed heartbeat | Abandoned lease/restart evidence and manual saved-configuration controls now tested; remaining timeout/rebinding/private-policy deployment acceptance |
| S05 | DeepSeek exact-decimal/currency fixtures, Qwen cash/credit distinction, ACS3 official vector, pinned endpoints | Unsupported capability and setup hints tested; Shared-account references and cross-component/currency guards tested; remaining deployment-specific non-production billing authorization |
| S06 | Confirmation/hysteresis reducer, incident transitions, maintenance and hourly aggregates | Partial-hour and missing/paused-time accounting plus both history charts tested; Retrospective full-hour corrections, expired-evidence fallback, multi-bucket evidence and retention boundary now tested; remaining broader failure-drill audit |
| S07 | Atomic immutable outbox, namespace preflight, same-occurrence retries, publisher revision fences and queue review | Two-component/two-OU inbox routing, duplicate/changed-content checks, restart lease retry, uncertain restore/discard and storm suppression now tested; remaining full sender-to-channel timeout/quota drill |
| S08 | Three-locale sandbox ZIP; admin component/monitor/grant/credential/operations UI; browser multi-monitor save | Form-error input retention/focus, duplicate-action guard, operations bridge budget, dark theme, locale switching and keyboard navigation tested; remaining broader accessibility/detail/export completeness |
| S09 | Private redirect and exact public proxy templates; real browser prefix/public-isolation check | Real nginx allowlist/assets/history passed CI at 05787ac; bounded peer/global rate budgets and forwarded-header bypass tests now pass; production capacity remains deployment-specific |
| S10 | Deterministic local ZIP and checksum; service Dockerfile/compose; independent version field | Immutable app release (development image build/non-root smoke passed CI), migration/index compatibility and operator upgrade/rollback |
| S11 | Local Go race/vet/build/vulnerability checks; CLI storage tests; frontend contract tests; five real browser scenarios | Full requirement-by-requirement audit, remaining failure drills and operator sign-off; first complete CI run passed at 636db6f |

No released app or production deployment is claimed. Keep the default Portal
market and deployment overrides unchanged until the release artifacts and this
ledger's remaining gates have been verified.
