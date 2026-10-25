# Status 0.1.0-beta.4 scope and release readiness

This candidate adopts shared SDK 0.2, reviewed and merged in
[Apps #19](https://github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/pull/19).
The common page shell, automatic panel-follow locale without a duplicate selector, labelled
fields, async resource lifecycle and bounded render-error fallback replace
duplicated Status implementations. The maintained demo and generated template
exercise the same presentation foundation; see the
[SDK ownership contract](sdk-foundation.md).

## Capabilities and operator scope

Provider adapters, backend APIs, component/finance authority and manifest scopes
are unchanged. HTTP, Dify read access, PostgreSQL SELECT 1, DeepSeek balance,
Alibaba/Qwen account billing and signed heartbeat remain the supported checks.
No model inference, write probe, new credential, recipient, publisher, anonymous
projection or automatic grant is added by this release.

The target already runs Beta.3 with four monitors and three sealed read-only
credentials. Its recorded post-upgrade scheduled samples and retained history are
documented in the [Beta.3 rollout](../apps/status/docs/react-ui-production-rollout.md).
Qwen billing credentials remain with the owner/account administrator for later
provisioning. An unsupported or absent billing identity never implies zero funds.
Notification publication remains paused under the owner's current decision.

The owner subsequently selected the internal OU for state visibility and accepted
browser acceptance rather than requiring a separate screen-reader sign-off for
this Beta. Those choices do not authorize finance grants, public exposure or
notification delivery. An unsaved deployment grant remains unsaved until its own
normal management flow is verified; release source does not write such policy.

## Host language and security compatibility

The minimum verified Portal remains published v2026.43.2. Hosts before the optional
locale field use the documented browser-language fallback. Portal v2026.43.7
supplies its selected language on the existing trusted `rp:init`/`rp:theme` bridge;
the SDK follows live updates automatically. Status has no independent language
selector. Language changes preserve active form drafts. The companion Portal
iframe color-scheme change and the SDK transparent startup surface address the
initial light canvas in a dark panel; production refresh verification remains a
rollout check.

The null-origin `allow-scripts` sandbox, host-only ephemeral tokens, bounded
parent/reply matching and current server authority remain unchanged. SDK 0.2
does not inject into host pages, weaken CSP or read browser storage/cookies.
Provider account amounts remain separately authorized and never enter the public
projection. All publication gates continue to require the shared frontend job.

## Source and browser acceptance

The shared-foundation source checks passed seventeen SDK tests, nine Status React
tests, two demo UI tests, workspace typechecks, 47 Python tooling tests and the
actual generated-template typecheck/test/build. The source PR's complete CI passed,
including the installed Status browser/accessibility matrix. The version-specific
exact-main CI and guarded release workflow repeat the relevant checks and all six
service artifact targets before immutable publication; an earlier source result
does not replace those release checks.

The browser matrix covers the released minimum Portal, current/disjoint OU reads,
account recreation, setup and draft/error behavior, independent resume controls,
themes, language and keyboard operation, 320-pixel/enlarged-text layouts, automated
WCAG scans, private/public boundaries, browser closure, independent service/Portal
outages, and disable/reinstall/uninstall. Automated browser evidence remains
distinct from an unperformed screen-reader certification.

## Storage, rollback and publication

There is no schema, storage-key, provider-secret or retention change. Preserve
independent data and keys and follow the
[market upgrade runbook](../apps/status/docs/upgrade-react-ui.md), applying its
pairing rules to Beta.3-to-Beta.4. A frontend replacement deliberately creates a
new installation identity; the existing backend must be re-paired rather than
accepting old tokens. The
[released lifecycle drill](../apps/status/docs/released-lifecycle-drill.md) proves
the previous actual released upgrade/rollback path in an isolated fixture; it is
not a claim that a future Beta.4 rollout has already happened.

The canonical catalogue retains verified Beta.3 while this candidate advances.
Its retained manifest was extracted from the checksum-verified public Beta.3 ZIP.
The guarded release must verify public metadata, every archive/ZIP and both image
executables before any catalogue update. Old release bytes remain immutable.
Production installation, exact bytes, pairing, data continuity and scheduled
samples must be recorded after publication; this document does not claim them.

## Current deployment constraints

The owner requires the server version configuration to remain unchanged and the
Portal deployment to use the beta channel consistently. This candidate does not
authorize changing a running server from its configured channel to a version pin,
changing the backend image reference or restarting it as part of a UI review.
Immutable release digests remain artifact-verification and recovery evidence;
they are not an instruction to rewrite the live deployment configuration.

The internal visibility decision is the existing OU named Anchan Internal
(`安禅内部` in user-facing directory data), for coarse component state/history and
incidents only. Resolve its actual opaque principal through the app directory.
Finance remains administrator-only, the public projection stays disabled and
notification publication stays paused. The owner accepts browser-based acceptance
for this Beta; a separate screen-reader sign-off is not a release prerequisite,
and no screen-reader certification is claimed.
