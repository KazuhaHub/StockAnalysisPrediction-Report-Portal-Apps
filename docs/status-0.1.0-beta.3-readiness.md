# Status 0.1.0-beta.3 scope and release readiness

This candidate applies the requested shared React/TypeScript/Ant Design standard
to both private and public Status pages. The reader overview concentrates on
availability and incidents. Administrative configuration uses separate tables,
progressive component setup, encrypted credential dialogs and independent probe
and notification resume choices. Source, SDK, template and required publication
gates are reviewed in Apps PR #13. The release workflow must repeat acceptance on
the exact main commit before any publication.

## Provider capabilities and deployment scope

Provider adapters and permissions are unchanged from Beta.2: HTTP, authenticated
Dify info, PostgreSQL SELECT 1, DeepSeek balance, Qwen billing and signed heartbeat.
The target deployment has four administrator-only monitors and three sealed
credentials. At the recorded production checkpoint all four checks had three
confirmed successes; see [the rollout record](../apps/status/docs/production-rollout.md).
The owner's authorization to retain those three existing read-only credentials
continues to apply. No new account, inference permission, public visibility or
notification recipient is introduced by this UI release.

Qwen still requires the owner/account administrator's billing identity. Ordinary
DashScope keys do not replace it. Real SMTP/Slack/Webhook delivery remains paused
and is not claimed. Owner-selected viewing/financial grants remain configurable;
no group is granted access merely because the UI is upgraded.

## Authority and sandbox isolation

The shared SDK checks the actual parent window, bounds request lifetimes and
pending requests and uses the existing viewer-bound bridge. Tokens, Portal DOM,
cookies and browser stores remain unavailable to app code. No same-origin sandbox
permission, CSP relaxation or Portal business-page modification is included.
Current account/OU, separate finance grants, public DTO redaction and installation
revocation remain enforced by the existing server contract. The minimum released
Portal remains v2026.43.2. Host locale is optional; older hosts use browser-language
fallback and an app override instead of claiming unsupported locale inheritance.

## Storage recovery and fault drills

There is no schema or storage-key change. Status keeps its independent SQLite
store, credentials and history. Snapshot/restore, key mismatch, single-owner and
paused-recovery tests remain required. Fifteen browser scenarios cover the real
minimum Portal bridge, separate OU readers, public projection, current identity,
probe scheduling across browser closure, Portal/Status outages and disable,
reinstall and uninstall. The release job repeats them and the isolated notification
capture/quota drill against this candidate's exact binaries.

A Portal app replacement deliberately revokes the old backend connection and
installation identity. Upgrade therefore requires an independent backup, a newly
reviewed pairing and preservation of the same Status database/storage key; see
[the upgrade runbook](../apps/status/docs/upgrade-react-ui.md). Previous deployment
receipts do not establish a future upgrade. Actual released Beta.2-to-Beta.3 upgrade
and rollback acceptance must be recorded after both versions are available.

## Accessibility

The React migration passed the fifteen browser scenarios locally, including
light/dark automated WCAG checks, keyboard controls, a 320-pixel view, enlarged
text and long labels. Public history drawer reflow was corrected after a failing
narrow-screen check. Dialog save errors retain the draft and remain visible inside
the dialog. The shared template is generated, typechecked, tested and built in CI.
Source preflight also passed 43 Python tooling tests, ten SDK tests, eight
Status React tests and two demo UI tests; exact-source CI remains a publication
requirement rather than being inferred from these local results.
Manual screen-reader and full native zoom certification remain explicit Beta
limits; automated checks do not establish those manual results.

## Operator review and publication gates

The owner requested a simpler Portal-consistent UI and a mandatory shared plugin
standard. Earlier authorization covers publishing/installing the Status Beta before
optional provider/recipient provisioning and deploying to the existing Portal.
The candidate stays within those permissions. No third-party account provisioning,
real message delivery, expanded OU grants or anonymous publication is inferred.

The record pins the same reviewed distroless runtime digest as Beta.2. The guarded
workflow requires the exact non-development manifest, all thirteen CI jobs
(including frontend-standard), all six artifacts and matching Linux image bytes.
Its write-capable job rechecks source, CI and artifact hashes. Existing tags,
releases, images and catalogue URLs are never overwritten. The market remains on
verified Beta.2 until Beta.3 public downloads and provenance are verified.


## Isolated configured-data compatibility preflight

A consistent copy of the running Beta.2 store passed SQLite integrity checks.
It contained four components, four monitors, three sealed credentials, zero grants
and 2,135 observations. A locally cross-compiled Beta.3 candidate from
`ae29a51372e9d6d03dda08ea2edda33bfa47ca9c` was exercised alongside the deployed
immutable Beta.2 image in disposable containers with `--network none`, a read-only
root filesystem, no capabilities and bounded resources. Only isolated copies were
writable; no server or provider worker was started.

Both versions backed up the copy. The candidate restored the old-version backup;
Beta.2 then reopened and backed up that restored store. Schema, configuration and
sealed-credential fingerprints, counts and all 2,135 observations matched. Restore
paused probes/outbox and disabled public projection as required. The production
Status process start time did not change. The protected checkpoint and verification
receipt are under `backups/react-compat-ae29a51/` in the existing Beta.2 deployment.
No credential or financial value is included here.

This is candidate CLI/storage compatibility evidence. It does not replace exact
released-byte verification, a real market upgrade, deliberate new pairing or a
post-publication rollback drill.
