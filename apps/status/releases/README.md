# Version-specific publication acceptance

The manual Release Status workflow requires `<version>.json` here, committed on
main with the matching non-development app manifest. No record exists for the
current development candidate. Creating a record means the referenced evidence
has been reviewed; a link alone never proves the underlying acceptance.

The JSON object has exactly these fields:

- `schema_version`: integer `1`.
- `app_id`: `status`.
- `version`: the exact manifest version, excluding development/snapshot builds.
- `minimum_portal_release`: a published Portal CalVer tag. The platform is now
  published and deployed as `v2026.43.2`; verify the selected release, not a branch.
- `runtime_image`: the approved `gcr.io/distroless/static-debian12:nonroot` image
  pinned with `@sha256:<64 lowercase hexadecimal characters>`.
- `evidence`: exactly `provider_capabilities`, `authority`, `storage_recovery`,
  `fault_drills`, `accessibility`, `operator_review`. Each value references reviewed
  HTTPS evidence or an existing `docs/` path relative to the repository root.

Do not enter placeholder evidence, manufacture operator approval or commit provider
credentials. Complete the acceptance ledger and actual environment checks first.
The workflow then downloads and verifies the selected Portal archive, exercises real
notification and browser integration, builds all six app archives and packages the
same Linux executable bytes into the image. A separate write-capable job rechecks
source and CI before publishing. It neither edits the catalogue nor switches the
Portal marketplace default.

A partial publication can reserve a tag, draft or image version. Existing versions
are never overwritten or automatically deleted. Inspect the evidence artifact and
current remote state, retain the failed attempt, and use a fresh version for another
publication. `verify-public` is read-only and may be used to repeat public download
verification against the original plan and finalized artifacts.
