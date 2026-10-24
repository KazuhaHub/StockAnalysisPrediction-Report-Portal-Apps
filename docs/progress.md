# Implementation evidence

## Baseline (2026-10-22)

- Shared repository name confirmed: StockAnalysisPrediction-Report-Portal-Apps.
- Owner selected public visibility.
- Portal notification PR #141 is open, mergeable and unmerged at inventory time.
- Portal default market remains its `apps/index.json`; no production override or
  production database was inspected. The market initially contains demo-symbols.
- Existing iframe isolation and bridge do not provide private external OU identity.
- Status and generic Portal connection storage proposal awaits explicit approval;
  no schema code or database has been created by the bootstrap.

## Work package status

S00 inventory in progress. S01 platform connection contract/storage is being
prepared. S02 repository bootstrap is independent preparatory work. S03-S11 remain
outstanding. No Status feature, live provider check or deployment is claimed.


## Bootstrap verification

- Catalogue/packaging tests: five tests passed; rebuilt demo ZIP has deterministic
  metadata, root manifest/entry, bounded assets and a SHA-256 sidecar.
- Shared request-bound assertion protocol: tests failed before implementation,
  then passed with race detection and vet. Replay storage is bounded and fails
  closed. This is a library, not a deployed Portal integration.
- Dify read probe verified against official current API documentation: authenticated
  `GET /v1/info` proves application-key/read access without running a workflow.
  Reference: https://docs.dify.ai/en/api-reference/guides/get-started
- DeepSeek account balance API verified against official documentation:
  https://api-docs.deepseek.com/api/get-user-balance/
- Alibaba billing account balance uses separate RAM authorization; the documented
  action is `bss:DescribeAcccount` (official spelling). This does not report an
  individual Qwen key's model quota. Reference:
  https://help.aliyun.com/en/user-center/developer-reference/api-bssopenapi-2017-12-14-queryaccountbalance
- Deployment-specific Dify version, Qwen account/site/credentials, installed Portal
  version and custom market override remain unverified. No production access was
  attempted and no genuine upstream credential is stored here.


## Published bootstrap and protocol work

The public repository was created and its bootstrap pushed on 2026-10-22. The
Portal default market URL and every deployment override remain unchanged.
Pinned legacy demo archive availability and its manifest ID/version/scopes were
verified over HTTPS; Python's local CA configuration failed, so the download was
verified with the system curl trust store without disabling TLS verification.

Seven catalogue/package tests now pass, including regressions that failed before
fixes for symlinked asset roots and release-tag/asset identity mismatch. The shared
protocol additionally provides a signed challenge/answer boot handshake, request
nonce replay protection and current-boot binding. A backend restart cannot accept
an assertion signed for the prior boot. Transport policy tests cover segment
boundaries, DNS pinning/mixed answers, private-network permission, reserved/metadata/
translation ranges, redirects, size limits and malformed JSON. These are reusable
library foundations; the Portal proxy is not wired or deployed yet.

Pending owner input: exact Portal/Status schema proposal. No schema code has been
written and no Status database was initialized. Complete S01/S02 implementation
continues after that decision. The full objective remains incomplete.


## Current viewer snapshot (2026-10-22)

The Portal branch now has an internal read-only account/OU projection primitive,
without routes or new tables. New tests first failed for the missing projection;
an invalid-expiry regression failed before fail-closed validation was added.
SQLite, focused race and real PostgreSQL cases prove current OU/role resolution,
account activation/expiry/password/session/deletion fencing, registration-bound
opaque identities and invalid ancestry/default refusal. Panel civil-date expiry
and cancelled context are covered. Full Go suite/build/vet/staticcheck passed.

This does not complete S01: token issuance still needs the current account cursor,
installation-generation checks and backend registry/proxy wiring. Exact storage
approval is still pending and no migration is written. The app-repository protocol
PR #1 head 28ee089 has passing GitHub Actions catalogue/protocol jobs. Production
market configuration, provider credentials and runtime have not been touched.


## Toolchain security gate

Portal draft PR #142's first go-test job stopped at govulncheck for standard-library
GO-2026-6809 under Go 1.26.9, before running its test suite. The minimum toolchain
in both Portal and the shared protocol module is now Go 1.26.10. The shared module
also gains the same govulncheck CI gate. Local scans with that exact compiler
report no reachable vulnerabilities; shared-module race tests and vet pass.
This does not approve or implement new storage. Owner schema approval remains
required before the dependent connection/persistence packages can proceed.
