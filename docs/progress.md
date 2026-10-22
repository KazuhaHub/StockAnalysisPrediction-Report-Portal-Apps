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
