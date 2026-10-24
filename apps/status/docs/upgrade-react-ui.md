# Upgrade and roll back the React UI release

## Boundaries

Beta.3 changes frontend code and shared development tooling. It does not alter the
Status database shape, storage key, provider credentials, grants, retention or
notification routing. Portal remains on its existing released version. Do not
restart Portal, Dify or PostgreSQL to install this plugin update.

Portal deliberately destroys the old backend pairing on app replacement. Keeping
a previous signing file alone does not restore the old installation identity.
A market upgrade must be followed by a reviewed connection registration and new
Status pairing pins. Data continuity comes from retaining the independent Status
database and its storage key, never from reusing an invalid installation token.

## Before making changes

1. Verify both releases' public metadata, ZIP/service checksums, source commits,
   minimum Portal version and image digests. Keep the Beta.2 image digest, Compose
   configuration and frontend ZIP as the rollback set. Do not use mutable tags.
2. Record configuration counts and stable monitor/component/credential IDs, grant
   counts, pause states and recent scheduled observations. Never write balance
   amounts, credential values or signing material into public evidence.
3. Pause probes for the maintenance window; keep notification publishing paused.
   Stop only the Status process before using its offline backup CLI. The CLI and
   server cannot open the same store concurrently.
4. Using the old image/binary and existing storage key, run `status backup` with
   `-database`, `-storage-key-file` and a fresh `-file` destination. Preserve that
   snapshot together with matching storage key, pairing/signing files, Compose
   configuration and gateway configuration in owner-only storage. Keep the
   reviewed Portal recovery/export procedure available for its app registration.
5. Verify backup hashes and SQLite integrity using an isolated copy. Keep restored
   work paused and do not connect that copy to real providers or notifications.
   A backup file existing is not sufficient recovery evidence.

## Upgrade through the market

1. Publish and verify Beta.3, then update the canonical catalogue in a separate
   reviewed change. The catalogue must never point at an absent release.
2. In Portal application management, fetch the market and review the Status
   version and unchanged `extension.read` / `extension.manage` permissions.
   Portal v2026.43.5 shows an installed badge rather than an upgrade action.
   With the verified backup available, use the Installed apps control to uninstall
   only the old Status frontend registration, fetch the market again and install
   the selected immutable release through its permission review. This creates a
   short frontend maintenance window; keep the independent service/data/keys.
   Do not delete the Status deployment or database. Do not upload an unverified
   development ZIP or modify installed database assets directly.

   This compatibility path is verified against the released Portal source. A
   future generic market-upgrade action can replace these frontend-only steps;
   this plugin release does not require a Portal business-code change.
3. Confirm the old app token/connection is denied. Register the backend for the
   new installation, explicitly preserving its narrow private network/port/route
   policy. Copy the new issuer/instance/audience/key ID and matching signing key
   into the protected Status pairing file through the normal pairing procedure.
4. Switch only Status to the verified Beta.3 image digest while mounting the same
   independent database, storage key and approved local PostgreSQL socket. Start
   one Status process, verify readiness and reopen the installed app.
5. Compare the stable IDs/counts, grants and pause states from the checkpoint.
   Confirm an ungranted reader still cannot view private/financial data. Review the
   operation state and resume probes only. Confirm three subsequent successes per
   configured monitor. Notification delivery and public projection remain paused
   unless separately authorized.
6. Record the actual market version, installed bytes, image digest, new pairing
   identity, health and continuity results in protected deployment evidence.
   Check Portal/Dify process start times to confirm they were unaffected.

## Rollback

If startup, rendering or continuity verification fails, pause/stop only Status and
retain diagnostic evidence. Reinstall the verified Beta.2 ZIP through the supported
Portal installer, review the same permissions and deliberately re-pair its new
installation identity. Use the old pinned image and the existing database only
if isolated old-version compatibility was verified. Otherwise restore the matching
pre-upgrade snapshot and storage key into an offline target using `status restore`.
Restore pauses work and requires review; do not automatically replay its outbox.

Verify readiness, stored identities/configuration and denied stale tokens before
resuming approved probes. Keep the failed candidate's data and receipts for review.
A catalogue pointer change alone does not downgrade an already installed app or
its independent service. Rollback never means mutating an old public release.
