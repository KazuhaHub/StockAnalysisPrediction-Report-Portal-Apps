# Status 0.1.0-beta.2 production rollout audit

This is the historical Beta.2 checkpoint. The subsequent
[Beta.3 React UI rollout](react-ui-production-rollout.md) records the installed
market update, preserved configured data and current operational boundaries.

Checked on 2026-10-24 UTC against GitHub release/PR state, the deployed service,
protected receipts and the existing administrator's native Chrome session.
This supplements the [original S00-S11 plan](../../../docs/implementation-plan.md)
and [requirement matrix](requirement-audit.md); it does not replace their scope.

## Verified installation and publication

| Item | Authoritative evidence |
| --- | --- |
| Immutable Beta | [status/v0.1.0-beta.2](https://github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/releases/tag/status/v0.1.0-beta.2), published 2026-10-24T09:57:23Z; source `00dd5d228bad00e983b7a7aff82ddf36e4dee215` |
| Exact-main source checks | [CI 40083339930](https://github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/actions/runs/40083339930), all twelve jobs passed |
| Publication checks | [Release 40083603968](https://github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/actions/runs/40083603968), six archives, released-Portal integration, both image executables and draft/public downloads verified |
| Canonical listing | [PR #11](https://github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/pull/11), merged as `6b28ffc3599e315062bceea94908949faab45d24`; [exact-main CI 40084444258](https://github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/actions/runs/40084444258) passed |
| Actual installer | Existing Portal application management UI refreshed the canonical catalogue, previewed `extension.read` / `extension.manage`, installed Status 0.1.0-beta.2 and displayed its installed row and market `Installed` state |
| Private registration | Existing Portal backend management UI saved and enabled the app-bound connection after pairing; native app reads and administrator operations subsequently succeeded |

The frontend came from the immutable market asset, not a manual upload or vendored
Portal source. Publication receipts and reserved unsuccessful Beta.1 attempts are
documented in [release readiness](../../../docs/status-0.1.0-beta.2-readiness.md).

## Running deployment

The target continues to run Portal v2026.43.5. This rollout did not rebuild,
downgrade or restart Portal. The service is independently deployed as
`report-portal-status`, with image:

```text
ghcr.io/kazuhahub/stockanalysisprediction-report-portal-apps/status@sha256:d846c4f0ba00d9d3642c94a7cab231ee8dc1380fa84cddfdb905ca529423407e
```

The Linux amd64 executable matches the release archive and CI executable:
`356e9a27123f00cc1e5ef6f95a2a1aeabe9a14645b046150dad5950e41bfc56a`.
The container runs as UID/GID 1001, with read-only root, all capabilities dropped,
no-new-privileges and bounded memory/CPU/process count. Its published listener is
loopback-only; the Portal connection allows only its fixed private network address,
port and reviewed relative methods/routes. The independent SQLite volume and
storage/signing keys are separate from Portal storage.

No persistent PostgreSQL proxy/helper container is required. The optional local
probe uses an explicitly mounted native PostgreSQL socket with a scoped read-only
identity. The [local transport acceptance](postgresql-local-socket.md) records the
actual SELECT 1 and negative controls. The formal service has no configured monitor
and therefore does not run that probe yet.

## Browser and route acceptance

The gateway's exact `/status` and `/status/` paths redirect to the authenticated
`/apps/x/status` application. Other `/status/` subpaths return 404; management and
public APIs are not exposed through this gateway. Normal Portal login/current OU
authority remains in control. The optional anonymous public mode is not enabled.

Native Chrome on the actual Portal rendered the Simplified Chinese overview,
empty-state explanation, administrator Manage navigation and Operations page.
Operations showed public publishing disabled and both probes/outbox paused.
After the independent Status restart, a fresh `/status` navigation and bridge read
returned the empty overview successfully. This proves installation, pairing and
current administrator reads; production OU grants have not been configured.

During browser automation the frame initially stayed blank. It rendered after
disconnecting the browser debugger attachment. The visible console contained an
unrelated extension's sandbox/localStorage exception, with no Status script error
observed. This is an observed sequence, not a proven browser root cause. An earlier
narrow framing-header experiment did not resolve the issue and was removed before
acceptance. The original asset CSP sandbox and framing headers are retained;
`allow-same-origin` was not added.

A native Chrome 200% zoom smoke check exposed the enlarged heading and navigation;
the screenshot was retained locally and the browser was restored to 100%. This
limited check is not full zoom/reflow certification or a manual screen-reader
audit. The existing fifteen browser scenarios cover the documented automated
accessibility, keyboard, 320-pixel and enlarged-text cases.

## Restart and recovery evidence

At 2026-10-24T10:30:03Z the target acceptance receipt recorded:

| Check | Result |
| --- | --- |
| Independent Status restart/readiness | Restart succeeded; `/readyz` returned 200 |
| Portal and Dify continuity | Their container start instants did not change; Portal health returned 200 |
| Unauthenticated private endpoint | `/v1/me` returned 401 |
| Disabled public website | Service `/` returned 404 |
| Public projection | `/public/v1/status` returned 200 with an empty list and total zero; it is not gateway-published |
| SQLite | Integrity check passed |
| Work queues | Probes/outbox paused; components, monitors, credentials and notification outbox each contained zero records |

Protected receipts reside in
`/data/report-portal/status-release-0.1.0-beta.2/`:

- `deployment-acceptance.json`
- `gateway-activation-verification.json`
- `frame-compat-rollback.json`
- `release-preparation-verification.json`
- `storage-initialization-verification.json`
- `backups/paired-infrastructure/verification.json`
- `DEPLOYMENT-RECOVERY.md`

The restricted infrastructure archive contains twelve named files: independent
database snapshot, matching keys/pairing, pinned Compose configuration, private
gateway include and receipts. Isolated extraction verified every per-file hash and
SQLite integrity. Archive SHA-256:
`c508f200d7d9d483e2f4f146233c5b21f56b65e24de2f678226b48e528d0eed2`.
The separate protected Portal pre-install backup remains available and is not
duplicated into this archive. No secret or backup content is published here.
This is same-host recovery verification, not an off-host disaster-recovery claim.

## Scope still open

The owner's install-first decision postpones configuration rather than declaring
it complete. The following remain explicit follow-up work:

1. Configure chosen components, read-only monitor credentials, thresholds and OU
   viewing/finance grants. Then review and resume probes and verify scheduled
   production observations. Earlier one-shot Dify/DeepSeek/PostgreSQL checks do not
   prove monitoring is configured in the formal service.
2. The owner/account administrator provisions the separate Qwen billing identity.
   Verify account/site/capability and read-only authorization afterward. Dify's
   DashScope model key is not used as a billing credential.
3. Choose Portal publication identity/rules and real recipient destinations before
   enabling notification publishing. Real SMTP/Slack/Webhook delivery is not claimed;
   isolated capture, retry, redaction and signed receiver drills remain the current
   implementation evidence.
4. Complete manual screen-reader and full native zoom/reflow review. The initial
   200% smoke observation does not establish that broader acceptance gate.
5. Verify released-version application upgrade/rollback when a subsequent reviewed
   version exists. Fresh installation and independent snapshot recovery do not
   establish compatibility with an uncreated future release.

Public activation and additional P1/P2 probes remain optional later work as scoped
in the original plan. The initial Beta rollout is verified; the full S00-S11
deployment acceptance is not declared complete while the listed checks remain.

## Authorized initial monitor configuration

After installation the owner explicitly authorized saving the existing Dify app key,
DeepSeek account key and dedicated PostgreSQL probe credentials in Status encrypted
storage for persistent read-only monitoring. No new provider credentials were created.
The transient private transfer file was removed after the normal app management UI
saved all three sealed credentials. No credential value appears in this repository.

At 2026-10-24T12:14:43Z, the protected `monitor-setup-acceptance.json` receipt recorded
Portal HTTPS readiness, authenticated Dify info, local Unix-socket PostgreSQL SELECT 1
and DeepSeek account balance as operational, each with three confirmed successes.
Portal/Dify/PostgreSQL intervals are 60 seconds with 5-second timeouts. DeepSeek
uses the reported CNY currency, a 300-second interval and 10-second timeout; its
zero-credit/recovery boundaries are 0/0.01 CNY. This does not establish model quota.

All four components remain administrator-only: zero direct/OU grants and zero
public components. Probes are enabled; notification publication remains paused,
with no configured publisher/recipient. Qwen billing setup and chosen OU visibility
are still pending. These observations supersede the earlier empty-store checkpoint
without changing its historical installation evidence.

The subsequent shared React/Ant Design UI migration remains development work until
its own complete browser, packaging and release gates pass. Production continues
to serve the immutable Beta.2 frontend during that migration.
