# Status 0.1.0-beta.3 publication checkpoint

Status Beta.3 was published at 2026-10-24T23:37:19Z as a non-draft prerelease:
[immutable release](https://github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/releases/tag/status/v0.1.0-beta.3).
The source is `d80858feedaec23cb68ab51f120555c0ded31e93`.
All thirteen [exact-main checks](https://github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/actions/runs/40142770938)
and the guarded [release workflow](https://github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/actions/runs/40143092234)
passed before this catalogue change.

## Verified immutable artifacts

The public release contains exactly ten assets: the frontend ZIP, six service
archives, build/release metadata and the checksum list. Independent public-download
verification compared every asset with the finalized workflow bundle. The metadata
binds the source, minimum Portal v2026.43.2, reviewed acceptance record and image.

- Frontend ZIP SHA-256: `c5dcbc8e328c97de799bd15b93da8df815601c176a6898c576b6e08358964a72`.
- Image: `ghcr.io/kazuhahub/stockanalysisprediction-report-portal-apps/status@sha256:b1a6cc38ab7d6299111c612994861538fea6c55a8f945996097f444c968d9e0d`.
- Linux amd64 executable SHA-256: `b52c3227b9141ee27fac3709b9a93068d4d7e17f3ae73f9136d7ccf7e0eb01be`.
- Runtime: `gcr.io/distroless/static-debian12:nonroot@sha256:afa5c872c891853ca7fcf1f12c3edb23f7eeef36189728842dd51042ff57f7ab`.

The release workflow compared both Linux architecture image executables with their
archives. On the target host the pulled immutable image independently supplied an
identical amd64 executable and reported version Beta.3 with network access disabled.
Its receipt is `backups/react-compat-ae29a51/released-image-verification.json` under
the existing protected Beta.2 deployment directory. No live data or keys were
mounted for that image check.

## Market and deployment boundary

The catalogue selects only this verified immutable Beta.3 ZIP, with unchanged
`extension.read` and `extension.manage` permissions. Published Beta.2 and the
retained demo archive are unchanged. The catalogue validator also checked both
actual public entries; 43 local Python tooling tests passed.

At this publication checkpoint production still ran Beta.2 with four configured
administrator-only monitors and three sealed credentials. Notifications remained
paused and public projection disabled. Pulling an image or updating a market entry
is not a completed runtime upgrade. The installer, deliberate new pairing,
configuration continuity and subsequent scheduled observations must be verified
through the [upgrade runbook](../apps/status/docs/upgrade-react-ui.md) before claiming
that rollout complete. Qwen billing credentials, owner-selected grants/recipients
and manual accessibility certification remain separate disclosed follow-up work.
