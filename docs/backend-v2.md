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

## Outbound HTTPS from a backend

A backend container has no network. A release that declares `network.proxy`
(see [descriptor-v2.md](descriptor-v2.md#forward-proxy-declaration)) can reach
reviewed HTTPS hosts through a forwarder that runs inside the container and
relays each connection over the runner's broker socket
(`PORTAL_APP_BROKER_SOCKET`). `packages/proxy` provides it.

When the release declares the capability, the runner sets, whether or not it is
granted, `HTTPS_PROXY` and `https_proxy` to `http://127.0.0.1:3128`, `NO_PROXY`
and `no_proxy` to `127.0.0.1,localhost`, and `PORTAL_APP_PROXY_LISTEN` to
`127.0.0.1:3128`. **`HTTP_PROXY` is not set**: only HTTPS traffic can use the
proxy, so use `https://` URLs; a plain `http://` request has no way out. Because
the variables are set without a grant, granting or withdrawing needs no restart.

Run the forwarder in one of two ways:

- **A resident Go backend** hosts it. Bind before starting any worker that
  needs the network, then serve:

  ```go
  import "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/proxy"

  l, err := proxy.Listen(proxy.Options{}) // PORTAL_APP_PROXY_LISTEN, loopback only
  if err != nil { /* fail the boot */ }
  go proxy.Serve(ctx, proxy.Options{Listener: l}) // PORTAL_APP_BROKER_SOCKET; returns when ctx ends
  ```

  `proxy.Serve(ctx, proxy.Options{})` alone listens and serves in one call.
  Add `COPY packages/proxy` to the image build and a `replace` for the module,
  as `apps/market-monitor/service` does.
- **No resident process**: ship the static `portal-egress-proxy` binary
  (`CGO_ENABLED=0 go build ./cmd/portal-egress-proxy` in `packages/proxy`) and
  start it before the code that needs it.

The forwarder accepts only HTTP/1.1 `CONNECT host:port` and answers anything else
with 405. A refusal by the broker comes back as `403` with
`X-Portal-Proxy-Refusal: <code>` and no body (`not_granted`,
`host_not_reviewed`, `port_not_permitted`, `address_denied`, `resolve_failed`,
`connect_failed`, `busy`, `budget_spent`, `unavailable`); until an administrator
has reviewed the hosts every CONNECT gets `not_granted`. Handle it like any
failing upstream. A TLS name that differs from the CONNECT host, or a first
record that is not a TLS ClientHello, shows up as a closed connection. The
forwarder holds no authority; every decision is the broker's.

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
