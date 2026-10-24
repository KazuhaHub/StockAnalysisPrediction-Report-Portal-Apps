# Portal and marketplace rollout evidence

Verified on 2026-10-24. This records the host prerequisite rollout; it is not
Status publication or activation.

## Published and deployed host

Portal [v2026.43.4 Beta](https://github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal/releases/tag/v2026.43.4)
is deployed on the authorized target. Its source is
`db8882b14dff6f7c3d36fa54bb8fbe2b76ba01aa`.

- [Exact-main full CI](https://github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal/actions/runs/40066113029)
  passed, including all four application race shards and cross-compilation.
- [Release workflow](https://github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal/actions/runs/40066645957)
  passed, including all six binaries, native ARM64 execution and image publication.
- The published Linux amd64 and macOS arm64 archives match `SHA256SUMS.txt`.
- Published metadata binds the source to image digest
  `sha256:aebb56b443291dcb4e6637d45ea6cdf08c66d9c52d45b9f51ed29c8bb289fa99`.
- The pulled, digest-pinned image's executable matches the published Linux binary:
  `8e1cc00e18c04ec9b88ccb9915084850ce915a4a19e3a3bfed405d05f96f580e`.
- The running version reports `2026.43.4 (db8882b, 2026-10-24T05:32:28Z)`.
  Container health and database health are both healthy.

The notification bell now follows the application launcher and precedes the
account menu, using a borderless button. A disposable local instance of the actual
release was inspected at desktop and 375-pixel widths. No production account was
created or reset for that review.

## Marketplace behavior

Portal #173 and #174 are merged. The compiled default is now the shared Apps
repository's `main/index.json`. Explicit administrator overrides and installed
applications remain unchanged. The target had no override before the upgrade;
the post-upgrade backup still has none, so the compiled canonical default applies.

Apps #4 supplies the reviewed legacy catalogue exporter and real browser market
acceptance. Its exact-source CI runs `40065577387` and `40065579673` passed; merged
main `fc4c1345b4de480233848f6940de6c4e9b774eb8` passed run `40065825246`.
The exporter preserves the old selection, archive paths and bytes rather than
copying all new capabilities into older installations.

All fourteen browser scenarios passed locally against checksum-verified published
Portal v2026.43.2, v2026.43.3 and v2026.43.4 binaries. This includes the actual
public catalogue and immutable demo ZIP, permission cancellation/confirmation,
an installed demo bridge query, current OU reads, account recreation, process
outages and app/backend lifecycle. CI continues to use the minimum v2026.43.2
release. These fixtures do not establish a production Status installation.

## Backup, recovery and continuity

Protected receipts and backups are on the target under
`/data/report-portal/backups/market-rollout-20261024T052627Z`.
They contain secret material and must not be uploaded as public artifacts.

The v2026.43.3 online snapshot was restored with both the old and new images into
separate SQLite databases, using CLI-only containers with no network. All 55
non-settings tables, totaling 45,771 rows, matched by row content. Integrity was
`ok`. All ten migration markers and their timestamps were preserved; the only
settings difference was the required notification dispatch pause after restore.
This verifies portable recovery into SQLite, not a live PostgreSQL disaster drill
or successful decryption of every saved credential.

Before deployment there were no unfinished analysis jobs. The original production
writer was stopped, a final snapshot was taken with the retained v2026.43.3 image,
and the pinned v2026.43.4 image was started. The final backup SHA-256 is
`acfaff45aec7ff4e24cf9542e427e07cefc498d066ec9c9183e97d72e38d644f`.

Post-upgrade comparison verified exact contents for reports (13,336), accounts
(10), organizational units (4), installed apps/files, notification events,
deliveries, channels and routing rules. Schema columns, all migration timestamps,
the saved market override and the operational dispatch setting were preserved.
The public home page, database health endpoint and all 64 referenced entry assets
returned successfully. Receipts distinguish these production checks from the
broader isolated restore comparison.

The deployment uses the existing Compose file plus
`/data/report-portal/deployment-release.override.json` to pin the release digest.
Use that override when reproducing this deployment; running only the original
Compose file follows its rolling image setting. The previous image and
infrastructure material are retained with the protected backup. Follow Portal's
recovery runbook for rollback and never erase migration markers.

## Remaining Status gates

The prepared Status candidate matches the successful exact-main Apps build at
`e1d735bbc15feb534c01ae38f0daeedadf4b7316` (CI `40061459868`). The server receipt
`status-candidate-f06279d/main-source-equivalence-e1d735b.json` records matching
frontend ZIP, Linux archive and image executable bytes. No replacement deployment
was necessary.

Status remains `0.1.0-dev`, unlisted, unpaired, stopped and operationally paused.
No gateway, production component grant or notification recipient was enabled.
Dify, DeepSeek and the scoped PostgreSQL target have the separately recorded
read-only capability evidence. The PostgreSQL gateway was subsequently removed
at the owner's request; [its runbook](postgresql-target-deployment.md) records
that monitoring now needs a replacement connection. Qwen billing RAM credentials remain the owner's
or account administrator's provisioning responsibility. Actual Qwen validation,
final version-specific acceptance, immutable Status publication, catalogue entry,
market installation, pairing and deliberate activation remain unfinished.
