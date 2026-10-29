# Experimental v2 presentation and own-backend transport

`@portal-app/sdk/bridge-v2` is SDK/root integration infrastructure, not a released
capability client or replacement for the legacy provider.
The development protocol is `portal.app.bridge/2-dev.2`. It is not frozen.

Use the [Portal transport contract and lifecycle guide](https://github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal/blob/kazuha/app-bridge-presentation/docs/app-platform/22-presentation-bridge-implementation.md)
for source ownership, state transitions, message bounds and integration rules.
Portal owns the module and common tests. Do not copy another bridge into an app
or independently edit the distributed source/test files here.

`createBridgeClient` takes the local Window, configured parent Window/origin and
an `onPresentation` callback. The callback receives readonly settings, display-only
context and an AbortSignal. Complete it only after the relevant DOM/React commit;
`setState` alone does not mean presentation is applied. A new host challenge
aborts old work and calls `onReset`, so the root can hide content while renegotiating.
Previous callback results cannot acknowledge or fail the successor session.

The panel supplies language, theme, timezone and layout. There is no separate
language-selection protocol, host token, raw credential or generic RPC escape.
Capability hints never grant API authority. There is no `rp:*`/v1 fallback.
Close the client on root disposal and handle fixed safe failure codes through
localized platform surfaces. Failed clients require an explicit fresh document.

Both roles exchange fresh document/channel nonces and use a dedicated MessagePort.
The host waits for the latest settings acknowledgement before initial reveal;
later updates coalesce without frame navigation. The actual shell loading cover,
before-paint CSS, React root, draft/history handling and real-browser acceptance
remain separate P06 work. Existing installed apps/providers are unchanged.

To change the transport, edit Portal's `web/src/lib/bridge-v2.ts` and tests, run
its contract generator with `--apps-dir`, and run both consumer test suites.
`python3 scripts/generate_app_contract.py --check` verifies exact source/test pins
offline. A schema/type regeneration in this checkout cannot silently repair a
modified bridge copy; regenerate from Portal instead. CI enforces this rule.

## Own-backend extension

The development `2-dev.2` protocol adds a required boolean `backend` to `app:init`
and exposes `context.backendAvailable`. This is a host availability hint, not a
capability grant or health assertion. `2-dev.1` does not silently negotiate this
extension; rebuild the development host and SDK together. Legacy apps are unchanged.

The ready client exposes `requestBackend({method, path, body}, signal?)`. The body
is an exact JSON string, not an object to serialize again. Methods are GET, POST,
PUT and DELETE; only bounded `/v1/` application paths are accepted and the
handshake operation is reserved. Server-side route/source/viewer checks remain
mandatory. Responses contain only validated `{status, body}`. No app URL, headers,
Cookie, viewer/OU claim, raw MAC, session credential or generic network permission
can be supplied. The private parent dispatcher always fixes the installation URL.

`backend.request`, `backend.cancel` and `backend.result` use the existing complete
binding and all document/channel nonces. Positive decimal request IDs increase
per connection; the host rejects replays. At most two calls per connection are
pending, with an independent two-call server budget. JSON request/response limits
are 64 KiB/1 MiB. Host work expires after 30 seconds and client waits after 35.
Cancellation aborts only the relevant dispatch. Closing/replacing a connection
aborts all its work and rejects outstanding requests. Late results cannot resolve
another channel's requests. Ordinary theme/locale changes preserve the channel.

Errors use `BridgeBackendError` and the closed codes `not_ready`, `unsupported`,
`invalid_request`, `busy`, `unavailable`, `uncertain`. Exception details never cross
the channel. `retryable` is false; the SDK performs no retries. In particular,
`uncertain` means a write may already have happened: retain the user's draft,
show a localized explanation, and offer a read-only state check rather than
silently resubmitting. Cancelling a submitted write does not prove rollback.

Use [the React backend hook](backend-v2.md) for application code. Do not construct
a second client inside the root. Source/test pin regeneration is unchanged.
