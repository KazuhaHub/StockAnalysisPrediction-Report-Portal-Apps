# Status artifact build and publication gate

Builds do not publish a Release/image or change the installation catalogue.
The Status app version comes from `apps/status/app.json`; the service executable
receives that exact version through its linker variable. There is no repository
wide application version.

## Build verified candidates

Use the Go version declared in the service module and Python 3.11 or newer:

```sh
python3 scripts/build-status-release.py
```

The default builds Linux amd64/arm64/armv7, macOS amd64/arm64 and Windows amd64.
For an individual candidate:

```sh
python3 scripts/build-status-release.py --target linux-amd64 --output /tmp/status-candidate
```

Artifacts are under `<output>/status/<version>/`:

- `status.zip`: sandbox frontend and its manifest, built from the same checkout.
- `status-v<version>-<os>-<arch>.tar.gz` or `.zip`: a single service executable.
- `build.json`: exact source commit, dirty-source flag, selected targets,
  required capabilities and an explicit `not-published` state.
- `SHA256SUMS`: hashes of every other file in that directory.

The command refuses existing nonempty output directories instead of replacing
candidate bytes. Use a fresh destination to rebuild. ZIP/tar/gzip timestamps,
file ownership and executable metadata are deterministic; binaries omit host paths
and build IDs. Builds use pure Go with workspace mode disabled. A failed build may
leave a partial candidate directory; never publish it. Remove only that disposable
candidate or choose a fresh output path, then verify a completed build.

CI builds all six targets, checks each checksum set, executes the native Linux
artifact's version command and retains candidates for seven days. CI artifacts
are development evidence, not immutable public release URLs.

## Publication prerequisites

Before the first app release:

1. Finish the acceptance ledger and review the independent storage/upgrade and
   operator recovery runbook.
2. Merge/release the shared protocol, Portal notification and backend platform
   dependencies through their own review process. Record the actual minimum
   released Portal version; `build.json` deliberately leaves it unset today.
3. Select a non-development Status version, update its manifest and release notes,
   rebuild from a clean reviewed commit and require all CI jobs on that commit.
4. Create an app-qualified immutable tag `status/v<version>`. Publish the verified
   ZIP, all selected service archives and matching checksums without replacing
   existing release assets. Publish the backend image independently and record
   its immutable digest.
5. Download and verify the published bytes/checksums. Install the ZIP through the
   real Portal installer against the released platform and exercise the runbook.
6. Only then add the immutable Status ZIP URL to the catalogue. The independent
   Portal default/override migration follows implementation plan section 14.2 and
   may precede Status publication when all currently listed apps are verified.
   A checksum file does not add host-enforced checksum verification to the
   existing marketplace.

No production/provider credential, recipient delivery or operator sign-off is
inferred from building candidates. No release, tag or image is created by this
script or the artifact CI jobs.

## Guarded manual publication

`.github/workflows/release-status.yml` is dispatched on main with `version`, the
matching `status/v<version>` confirmation and release notes. It requires the
version-specific record described in `../releases/README.md`; the current
`0.1.0-dev` manifest is deliberately refused. Do not dispatch a production release
until the record's evidence and all remaining environment acceptance are complete.

The read-only job requires successful exact-main push CI, builds all six targets,
and runs real browser/notification acceptance using the verified binary from the
selected published Portal release. The write job checks source and CI again,
refuses an existing image/tag/release, publishes a digest-pinned runtime with the
prebuilt Linux executables, compares both image binaries with the archives, binds
the digest and compatibility evidence in `release.json`, and verifies every draft
asset by downloading it before publication. Public downloads are checked again.
There is no rolling image tag and no automatic catalogue/default-market edit.

GitHub retains the verified candidate bundle for fourteen days and the publication
bundle for thirty days. Preserve the original plan and finalized artifacts for
operator recovery. A partial failure does not replace or erase remote versions;
review current state before using a new version. Never rerun blindly to repair an
existing image or draft. Policy unit tests exercise unsafe archives, tampered
metadata, missing targets, source admission and failed-upload draft retention.
The workflow implementation is not evidence of an actual completed publication.
