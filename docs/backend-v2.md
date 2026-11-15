# Experimental React own-backend client

This is a development-only addition to `@portal-app/sdk/root-v2`. It does not
publish a stable SDK, migrate maintained apps, install a backend or enable
production execution. Keep the public template/catalogue/releases unchanged
until complete platform acceptance. Use one `AppRoot` and the shared React/Ant
foundation; never copy the transport into an app.

## Read from the application's backend

```tsx
import { useEffect, useState } from 'react';
import { Alert, Spin, Typography } from 'antd';
import { useAppBackend, useAppPresentation } from '@portal-app/sdk/root-v2';

export function Notes() {
  const { ready, available, request } = useAppBackend();
  const { presentation } = useAppPresentation();
  const [data, setData] = useState<unknown>(null);
  const [failed, setFailed] = useState(false);
  const copy = {
    'en-US': { unavailable: 'App backend unavailable', failed: 'Could not read app data' },
    'zh-CN': { unavailable: '应用后端暂不可用', failed: '无法读取应用数据' },
    'zh-TW': { unavailable: '應用程式後端暫不可用', failed: '無法讀取應用程式資料' },
  }[presentation.locale];
  useEffect(() => {
    if (!ready) return;
    const abort = new AbortController();
    setFailed(false);
    request({ method: 'GET', path: '/v1/notes', body: '' }, abort.signal)
      .then(result => {
        if (abort.signal.aborted) return;
        if (result.status === 200) setData(JSON.parse(result.body));
        else setFailed(true);
      })
      .catch(() => { if (!abort.signal.aborted) setFailed(true); });
    return () => abort.abort();
  }, [ready, request]);
  if (!available) return <Alert type="warning" title={copy.unavailable} />;
  if (!ready) return <Spin />;
  if (failed) return <Alert type="error" title={copy.failed} />;
  return <Typography.Paragraph>{JSON.stringify(data)}</Typography.Paragraph>;
}
```

`available` is the host's boolean hint. `ready` becomes true only after initial
React/Ant presentation commit and the client's ready acknowledgement. Both must
be true before initial automatic reads. `request` stays stable during ordinary
presentation changes, so language/theme updates do not repeat the effect. A new
host connection aborts the old signal and remounts application state. Unmounted
or retired hook references refuse new calls. A caller's AbortSignal is combined
with the document's signal; it cannot outlive that document.

## Writes and result handling

Write only from an explicit user action, never a mount effect. Set a submitting
state before calling `request`, prevent duplicate clicks and preserve the draft
until a confirmed result. Pass a JSON string as `body`, using `JSON.stringify`
exactly once at the application boundary. App HTTP error statuses are returned
inside `{status, body}`; handle 400/403/404/409/422/429 as app business responses.
They are not Portal session errors. Parse only the app response shape that the
application itself defines.

Transport failures throw `BridgeBackendError` from `@portal-app/sdk/bridge-v2`.
Use its code for localized UI, not `error.message`. `uncertain` means a submitted
write might have completed despite the lost response or revoked access. The SDK
never retries. Keep the input, explain the uncertainty in all three supported
locales, and offer a read-only refresh or a deliberate business reconciliation
flow. Do not automatically resubmit after timeout, cancellation, page refresh or
connection replacement. A request ID is a channel correlation ID, not a business
idempotency key. Apps requiring business deduplication must implement that in
their own approved storage and backend API.

`not_ready`, `unsupported`, `invalid_request`, `busy` and `unavailable` are fixed
safe codes. No exception text, internal hostname, socket path, credentials or
user identity is returned. The API has no arbitrary URL/header option. Do not
fetch Portal session endpoints, read parent DOM/storage or construct a legacy
PortalClient as a fallback. Platform capabilities remain separate and default
to denied; this channel accesses only the current installation's own backend.

## Validation

The common host/client corpus is generated from Portal and pinned byte-for-byte.
It covers exact UTF-8 JSON strings, capability-independent backend access,
closed schemas, unsupported/unready clients, stale envelopes, replayed IDs,
concurrency, cancellation, timeouts, retirement, sanitized errors and no retries.
React tests verify ready-after-ack, stable request identity across live
presentation changes, abort propagation and rejection after unmount. Node
MessagePort/jsdom tests are not rendered-browser or production acceptance.
Run the shared SDK, root build, template, demo and Status consumer checks listed
in `root-v2.md`. The Portal host adapter additionally tests bounded fetch
responses, immutable installation destination, session expiry and ambiguous IO.
