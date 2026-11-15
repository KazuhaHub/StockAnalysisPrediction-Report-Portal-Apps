# Experimental current-viewer reports client

This is a development-only addition to `@portal-app/sdk/root-v2`. It does not
publish a stable SDK, grant background report access or replace the Portal
report viewer. The current installation must have a granted `reports.read`
capability. Every read is still authorized by the Portal against the current
session, installation binding, policy revision, release and owner scope.

Use one `AppRoot` and `useAppReports`; do not copy the bridge, construct request
messages, call a Portal report route or add a viewer/tenant identity field.

## List and open reports

```tsx
import { useEffect, useState } from "react";
import { Alert, Spin, Typography } from "antd";
import {
  BridgeReportError,
  useAppReports,
  useAppPresentation,
  type AppReportDetail,
  type AppReportList,
} from "@portal-app/sdk/root-v2";

export function RecentReports() {
  const reports = useAppReports();
  const { presentation } = useAppPresentation();
  const [list, setList] = useState<AppReportList | null>(null);
  const [detail, setDetail] = useState<AppReportDetail | null>(null);
  const [failure, setFailure] = useState<"unavailable" | "uncertain" | null>(
    null,
  );
  const copy = {
    "en-US": {
      unavailable: "Reports are unavailable",
      retry: "Could not load reports",
    },
    "zh-CN": { unavailable: "报告不可用", retry: "无法加载报告" },
    "zh-TW": { unavailable: "報告不可用", retry: "無法載入報告" },
  }[presentation.locale];

  useEffect(() => {
    if (!reports.ready) return;
    const abort = new AbortController();
    reports
      .query({ date: "today", limit: 20 }, abort.signal)
      .then((result) => {
        if (!abort.signal.aborted) setList(result);
      })
      .catch((error: unknown) => {
        if (abort.signal.aborted) return;
        if (
          error instanceof BridgeReportError &&
          (error.code === "unavailable" || error.code === "uncertain")
        )
          setFailure(error.code);
      });
    return () => abort.abort();
  }, [reports.ready, reports.query]);

  if (!reports.available)
    return <Alert type="warning" title={copy.unavailable} />;
  if (!reports.ready || (!list && !failure)) return <Spin />;
  if (failure) return <Alert type="error" title={copy.retry} />;
  return (
    <>
      {list!.items.map((item) => (
        <button
          key={item.id}
          onClick={() =>
            void reports.get(item.id).then((result) => {
              if (result.kind === "get") setDetail(result.report);
            })
          }
        >
          {item.title}
        </button>
      ))}
      {detail && (
        <Typography.Paragraph>{detail.bodyMarkdown}</Typography.Paragraph>
      )}
    </>
  );
}
```

`query({symbol?, q?, kind?, subtype?, date?, since?, until?, limit?, offset?})`
returns `{kind: "query", count, total, offset, limit, items}`. `limit` is 1 to
50 and defaults to 20. `date` accepts an exact `YYYY-MM-DD` date or `today`, using
the Portal's configured report timezone. `since` and `until` select a date range.
Use pagination rather than increasing the limit.

`get(id)` returns `{kind: "get", report}` with summary metadata and
`bodyMarkdown`. A missing report and another current viewer's report both return
`unavailable`, so the app cannot use detail reads to enumerate tenant data.

## Authority and lifecycle

The hook exposes only `available`, `ready`, `query` and `get`. It never accepts a
URL, Cookie, session token, actor, owner scope or arbitrary installation. The
Portal fixes the installation destination and rechecks the complete launch
binding before and after each read. Results are discarded if scope, policy,
release, current session, capability grant or owner scope changes while the read
is in progress.

`available` reflects the exact `reports.read` grant advertised for this
connection. `ready` becomes true only after the initial React/Ant presentation
commit and bridge acknowledgement. Start automatic reads only after `ready`.
The query/get functions stay stable across ordinary language and theme updates.

Caller cancellation is combined with the document lifetime. Unmount, connection
replacement, capability revocation or a new launch generation rejects old
closures with `not_ready`; their late results cannot repopulate the new
presentation. Do not cache a report across a fresh `AppRoot` session.

## Failure semantics

Errors are `BridgeReportError` with `not_ready`, `unsupported`,
`invalid_request`, `busy`, `unavailable` or `uncertain`. Use the code for
localized UI, never `error.message`. Do not automatically retry `uncertain`;
offer an explicit refresh. Report reads have no write effect, but retrying still
risks stale or cross-scope content if the session changed.

Markdown is data, not executable HTML. Render it with a Markdown renderer that
does not inject raw HTML, or sanitize it before rendering. Do not pass
`bodyMarkdown` to `dangerouslySetInnerHTML`. Links and images remain subject to
the application sandbox and Portal policy.

This client reads the current viewer's visible reports only. It is not a
background worker, service credential, report writer, export API or replacement
for a separately reviewed service grant.

## Validation

Portal owns the bridge channel, current-viewer resource route and shared
source/test corpus. The contract generator copies and pins those bridge files
into this repository:

```sh
python3 scripts/generate_app_contract.py --check --apps-dir ../Portal-Apps-v2-work
npm test --workspace=@portal-app/sdk -- --run tests/bridge-v2.test.ts tests/reports-hook.test.tsx
npm run typecheck --workspace=@portal-app/sdk
```

Portal host tests cover revoked grants, old generations, two-owner-scope
isolation, denied detail enumeration and scope changes during reads. Shared
bridge tests cover unavailable/unsupported calls, invalid input, stable errors,
cancellation, pending-request ceilings, replayed IDs, old closures and no
automatic retries. These tests are not a substitute for real browser acceptance
with a signed local candidate.
