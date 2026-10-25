# Experimental v2 presentation transport

`@portal-app/sdk/bridge-v2` is SDK/root integration infrastructure, not a finished
React root, business API or released replacement for the legacy provider.
The development protocol is `portal.app.bridge/2-dev.1`. It is not frozen.

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
