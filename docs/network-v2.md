# Experimental reviewed network client

This is a development-only addition to `@portal-app/sdk/root-v2`. It does not
freeze the network API, grant a destination, install a runner or approve production
use. The current installation must have a granted `network.http` capability and a
reviewed policy. Use one `AppRoot` and the shared hook; do not copy the bridge,
construct Base64 manually or call a Portal route directly.

## Read an approved HTTPS endpoint

```tsx
import { useEffect, useState } from 'react';
import { Alert, Spin, Typography } from 'antd';
import { useAppNetwork, useAppPresentation } from '@portal-app/sdk/root-v2';

export function StatusSummary() {
  const network = useAppNetwork();
  const { presentation } = useAppPresentation();
  const [summary, setSummary] = useState('');
  const [failed, setFailed] = useState(false);
  const copy = {
    'en-US': { unavailable: 'Network access is unavailable', failed: 'Could not load status' },
    'zh-CN': { unavailable: '网络访问不可用', failed: '无法加载状态' },
    'zh-TW': { unavailable: '網路存取不可用', failed: '無法載入狀態' },
  }[presentation.locale];

  useEffect(() => {
    if (!network.ready) return;
    const abort = new AbortController();
    network.request({
      method: 'GET',
      url: 'https://status.example.com/api/summary',
      accept: 'application/json',
      contentType: '',
    }, abort.signal).then(response => {
      if (abort.signal.aborted) return;
      setSummary(new TextDecoder('utf-8', { fatal: true }).decode(response.body));
    }).catch(() => {
      if (!abort.signal.aborted) setFailed(true);
    });
    return () => abort.abort();
  }, [network.ready, network.request]);

  if (!network.available) return <Alert type="warning" title={copy.unavailable} />;
  if (!network.ready) return <Spin />;
  if (failed) return <Alert type="error" title={copy.failed} />;
  return <Typography.Paragraph>{summary}</Typography.Paragraph>;
}
```

`request` accepts `{method, url, accept?, contentType?, body?, credential?}`. `body` is a
`Uint8Array`; the hook performs bounded Base64 conversion. `accept` defaults to
`application/json`. The response is `{status, contentType, body}`, where `status`
belongs to the remote service even when it is 401, 403, 429 or 500. Parse only the
business response shape your app defines.

`credential` is a stable binding name, never a secret value. It is accepted only
when both `network.http` and `secrets.use` are current; `credentialAvailable`
reports the latter. Portal resolves the exact installation binding, reviewed
operation and credential revision on every request, then injects one fixed
`Authorization: Bearer` or `X-API-Key` header in the private runner exchange.

The hook never accepts arbitrary headers, actor/controller/review fields,
credential bytes, private addresses or a replacement host route. HTTPS,
destination, method, DNS, redirect, binding and current grant checks remain
server-side. A caller's AbortSignal is combined with the presentation lifetime.
Unmount, channel replacement, capability change or presentation retirement
rejects old closures.

## Failure semantics

Errors are `AppNetworkError` values with `not_ready`, `unsupported`,
`invalid_request`, `busy`, `unavailable` or `uncertain`. Never display
`error.message`. Never retry `uncertain`: the remote service may have completed a
write before the response was lost. Preserve the user's draft and offer an
explicit reconciliation or read-only refresh.

Cancellation prevents an outstanding local request from resolving and aborts the
Portal fetch. It cannot prove that a remote side effect did not happen. Request IDs
correlate one document channel; they are not business idempotency keys.

The Portal adapter fixes the current installation route, uses same-origin cookies
only for that Portal call, disables redirects and caching, streams JSON under a
fixed bound and strictly parses the response envelope. A remote 401 does not sign
out the Portal viewer. Portal 401/session expiry is a separate host failure.

## Validation

Portal owns `network-v2.ts`, the bridge channel and common tests. The contract
generator copies and pins the network source/test into this repository. Run:

```sh
python3 scripts/generate_app_contract.py --check --apps-dir ../Portal-Apps-v2-work
npm --prefix packages/app-sdk test
npm --prefix packages/app-sdk run typecheck
```

The shared tests cover binary boundaries, closed wire fields, unsupported and
ungranted calls, duplicate viewport/connection envelopes, independent backend
IDs, cancellation, timeout/late results, flood ceilings, credential-name-only
requests and no automatic retry. React tests cover ready-after-ack, binary
conversion, stable hooks across appearance updates and rejection after document
retirement. Node MessagePort and jsdom tests are not a substitute for the real
browser/native acceptance.
