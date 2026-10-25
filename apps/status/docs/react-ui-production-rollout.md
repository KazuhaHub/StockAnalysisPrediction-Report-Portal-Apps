# Status Beta.3 React UI production rollout

This record supplements the historical [Beta.2 rollout](production-rollout.md)
and [publication checkpoint](../../../docs/status-0.1.0-beta.3-publication.md).
The upgrade followed the [market upgrade runbook](upgrade-react-ui.md). It changes
the plugin frontend and runtime assets without changing Portal business code or
the Status database shape.

## Installed artifacts and unchanged boundaries

The actual Portal application market installed `0.1.0-beta.3` from the canonical
Apps catalogue after displaying its unchanged `extension.read` and
`extension.manage` permissions. The installed row and application header both
displayed Beta.3. Every served frontend asset was independently compared with
the checksum-verified public release ZIP:

| File | SHA-256 |
| --- | --- |
| `app.js` | `3082b74f34a1fb3f0b12ff4b52ba22b8513f91afdcc693819b77511fffa5c97d` |
| `index.html` | `0a9bc9765fdde29178776481d98942829d4c729e63255dfa86a05ec4cd9b4a7d` |
| `style.css` | `dc4365c9e59546a3915179f125293232380ac5cf1e84f0662415cdbfd3c91823` |

The independent service started at `2026-10-25T00:02:47.347093218Z` with image
`ghcr.io/kazuhahub/stockanalysisprediction-report-portal-apps/status@sha256:b1a6cc38ab7d6299111c612994861538fea6c55a8f945996097f444c968d9e0d`.
Readiness returned HTTP 200. Its fixed private address, loopback publication,
read-only native PostgreSQL socket, non-root identity and container hardening
were retained. No PostgreSQL helper container was introduced.

Portal already ran v2026.43.6 before this Status maintenance window. Its process
start time remained `2026-10-24T23:48:23.605750114Z`; this rollout neither upgraded
nor restarted Portal. Existing Dify API/worker processes also remained running.

## Backup, continuity and deliberate pairing

The old native Status Operations UI saved probes paused while leaving notification
publication paused. Only Status was stopped. The released Beta.2 offline backup
command created a consistent snapshot at `2026-10-25T00:01:31Z`. SQLite integrity,
configuration fingerprints and sealed credential rows were checked before copying
that snapshot into the new deployment directory. The protected rollback set includes
the matching storage/signing keys, previous pairing and Compose configuration.

| Preserved data | Count |
| --- | ---: |
| Components | 4 |
| Monitors | 4 |
| Sealed credentials | 3 |
| Component grants | 0 |
| Historical observations | 2,297 |
| Incidents | 0 |
| Notification outbox entries | 0 |

Stable component/monitor identities, monitor configuration, sealed credentials and
grants were identical after startup. Every pre-upgrade observation ID remained
present. Runtime scheduling fields were excluded from configuration comparison.

The supported frontend replacement flow cleared the previous backend registration.
The new installation was registered through Portal's Backend dialog and deliberately
paired using its newly displayed installation identity. The existing signing key,
audience, exact private destination and narrow route policy were retained. The
connection stayed disabled until the new pairing file was saved. No database asset
replacement, cookie extraction or expanded access was used.

Protected deployment evidence is kept under the Beta.3 deployment's
`backups/upgrade-20261025T000131Z`, `upgrade-checkpoint.json` and
`rollout-receipt.json`. Credentials, balances and signing material are intentionally
excluded from this public record.

## Native UI and continuous probes

Native Chrome rendered the installed React/Ant Design application in the existing
Portal sandbox. Simplified Chinese selection, the four-service overview,
administrator component table and separate Operations controls were exercised.
All components remained administrator-only. No host CSP or sandbox relaxation was
needed. As with Beta.2, an attached browser debugger initially left the frame blank;
the native page rendered after detaching and reloading. This sequence does not
establish the browser root cause.

The resume dialog selected probes only and reviewed the empty outbox; notification
publication was not selected. The saved service settings confirmed
`probes_paused=0`, `outbox_paused=1`, and `public_enabled=0`. The scheduler produced
fresh successful HTTP, Dify, PostgreSQL and DeepSeek observations without manual
probe submission. Subsequent scheduled-cycle confirmation is recorded separately
in the protected receipt; an initial success alone is not final continuity evidence.

## Limits and remaining configuration

Qwen billing still awaits the owner's Alibaba read-only billing identity. Existing
model keys do not prove billing capability. No recipients or notification publishers
were configured, no real notification was sent, no OU/finance grant was added, and
anonymous publication remains disabled. These optional choices are independent of
the installed UI update. Manual screen-reader certification remains unverified.

Both actual released service executables completed an isolated backup/restore and
old-version reopen drill against a protected copy of configured data. Restores
remained paused with public projection disabled. This demonstrates released storage
compatibility; it does not claim that a production market downgrade was performed.
The retained immutable Beta.2 artifacts and deliberate re-pairing procedure remain
the rollback path.

The subsequent [released lifecycle drill](released-lifecycle-drill.md) exercised
the normal installer with both actual immutable ZIPs and native service archives
in an isolated Portal v2026.43.2 fixture. Upgrade and rollback preserved a saved
component, disabled monitor and sealed credential, required distinct pairing
identities and rejected stale tokens. Production remained on Beta.3 throughout.
