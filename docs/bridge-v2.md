# Experimental v2 presentation and own-backend transport

`@portal-app/sdk/bridge-v2` is SDK/root integration infrastructure, not a released
capability client or replacement for the legacy provider.
The development protocol is `portal.app.bridge/2-dev.8`. It is not frozen.

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

## Reviewed network extension

Development protocol `2-dev.8` adds `network.request`, `network.cancel` and
`network.result`. The host advertises `network.http` only when the current
installation has a granted, reviewed network policy. Use
[`useAppNetwork`](network-v2.md); never construct these messages in application
code.

Network and own-backend request IDs are independent monotonic sequences with
separate pending maps. Each connection allows two requests per channel. Network
requests use exact `method/url/accept/contentType/bodyBase64` fields, UTF-8 JSON
below 64 KiB and binary responses below 1 MiB. Parent/current binding, channel
nonce, grant and current server-side policy are all rechecked by the host and
Portal. Remote 401/403 statuses remain application responses; only a Portal
session failure invokes the host's session-loss handler.

An `uncertain` network result may follow a completed remote write. Neither side
retries automatically. Closing, capability changes or a replacement document
abort pending work and reject old closures.

## Document sizing extension

Development protocol `2-dev.3` adds `layout.measure` and
`client.reportDocumentHeight(height)`. The shared root measures its natural
flow-root border box after commit/ready, observes content/width changes and
reports integer CSS pixels, 0..100000. Body/HTML own no document scroll; the
Portal content region is the document scroll owner. Do not use `100vh`, viewport
min-height or size-to-parent loops in document content. Dialog overlays are not
part of natural flow. A viewport app owns its bounded editor/list region instead.

Measurements carry the complete channel binding, an increasing measurement
revision and the applied presentation revision. Old generations, old revisions
and measurements during a superseded presentation cannot resize the current
page. Both client and host coalesce to at most ten applied heights per second;
the host fails a channel exceeding twenty valid-envelope measurements per
one-second receive window. Non-finite, negative, fractional and oversized heights
are rejected; content above the limit must use virtualization/viewport mode.
Pending observers/timers retire with the document. Size changes do not reload
frames, rerun initial backend reads or change capabilities.

The host holds the initial document cover until presentation plus the first
measurement; a missing first measurement fails after ten seconds with explicit
retry. A minimum 64px host surface accommodates empty apps. Heights may both grow
and shrink. This adds no host DOM access to the child and does not weaken the
opaque iframe sandbox. Rebuild the development host and SDK together; previous
protocols do not silently receive the new control message.


## Unsaved-change extension

Development protocol `2-dev.4` adds child-to-host `draft.changed` with the exact
current channel envelope, a canonical increasing positive int64 `revision` string
and boolean `dirty`. Extra fields (including text, URLs and prompt callbacks) are
rejected. A stale envelope/revision cannot update the current document's hint.
The SDK aggregates form owners; the low-level client exposes `setDraftDirty`.
It returns false before readiness or after retirement and coalesces reports to
at most ten per second. The host rejects more than twenty increasing reports in
one second. This hint conveys no authority and contains no draft body.

The host clears the hint on reload, failure, activation replacement and unmount.
It uses its router blocker and localized Ant modal; apps cannot veto a confirmed
leave or choose a destination through this extension. No persistence or signed
in-app history navigation protocol is introduced. This development bump requires
matched host/SDK sources; there is no fallback to an earlier v2 revision.


## Registered navigation extension

Development protocol `2-dev.5` adds optional validated presentation `navigation`
with exact `path` and `routes`. Routes contain only signed `id`, `path`, `layout`,
with unique IDs/paths, a `/` route and a maximum of 32. The active path must exist
and its signed layout must equal presentation layout. Hosts obtain this registry
from the current authenticated launch admission, never from a child message.
Consumers without navigation keep the presentation-only behavior.

`navigation.request` carries the exact current channel envelope, independent
canonical increasing int64 `revision`, current `presentationRevision`, exact
registered `path` and boolean `replace`. Stale channels/revisions, queued or
unacknowledged host presentations cannot dispatch a navigation. Unknown paths or
extra payload fields fail the channel. Requests are bounded separately from
height and draft messages. No URL, query object, callback, HTML or app-owned
history object crosses the boundary.

The client exposes `navigate`; the host exposes `onNavigate`. Sending is not
commit acknowledgment. The host router remains authoritative and may show its
unsaved-change prompt. The later presentation reports only the committed path.
App callbacks cannot block a confirmed leave. There is no automatic replay after
cancel, timeout, channel replacement or failure. No descriptor/storage schema is
changed and no query syntax is implicitly authorized by this development step.


## Typed-query development extension

Protocol dev.6 adds mandatory canonical `search` to navigation presentations and
requests. Route descriptors optionally include signed typed query rules; the
shared pure validator handles the descriptor, host, SDK request and URL read
boundaries consistently. `useAppNavigation()` exposes a readonly typed query and
canonical search; requests take `{replace?,query?}`. Empty query clears state.

Only declared fields cross the boundary. Canonical search order/encoding, duplicate
refusal, numeric/boolean type and range checks, UTF-8 text bounds, finite enum
choices and a 2048-byte total budget prevent alternative or unbounded states.
The host validates canonical search against the current signed destination route
before navigation; the committed presentation is independently parsed by the
child. Query changes do not create a new iframe, metadata request, root epoch or
backend write. A stale/canceled request does not change the SDK's query.

The descriptor schema extension is experimental and signed as release bytes; it
is not a database schema or stable SDK freeze. Existing declarations without
query rules retain an empty allowed query set. Existing package bytes, signatures,
legacy SDK providers and catalogue entries are not rewritten or published.


## Shared page actions (development)

`useAppPage` from `@portal-app/sdk/root-v2` declares the Portal-owned title,
description and up to six actions. Mount one descriptor inside AppRoot and omit
a duplicate inner page header. Example:

```tsx
useAppPage({ title: translatedTitle, actions: [{
  id: 'refresh', label: translatedRefresh, variant: 'primary',
  onAction: async signal => { await reload(signal); },
}] });
```

Title/description/actions default to empty, variant to default, disabled/loading
to false. IDs are unique lowercase ASCII identifiers (at most 32 characters);
labels are nonblank (48 Unicode scalar values), titles 80, descriptions 240,
with one primary action at most. Control/directional formatting and malformed
Unicode are rejected. Only plain text crosses the channel; callbacks stay local.
Use Portal locale values to translate application-owned copy.

The dev.7 host and SDK must be used together. Page descriptions and action
invocations carry the full bridge binding/nonces, owner scope and independent
revision IDs. The host checks committed appearance; the client checks the latest
published page and current action flags. One action runs at a time, with fixed
completion or uncertainty and no automatic retry. The client deadline is 25s,
host 30s. Pass the callback AbortSignal to backend work; cancellation cannot undo
an already committed transaction. Await/check backend responses before resolving
the callback.

Route/query changes, page owner replacement, reload and close retire old buttons
and abort their cooperative work. Locale/theme updates preserve ownership and
ongoing operations. Updating loading/disabled metadata does not cancel a running
action. Removing that action does. Old results cannot complete a successor page.
StrictMode cleanup is fenced so it cannot clear a successor route descriptor.

This remains a development API. Whole platform acceptance, D5, stable SDK freeze,
production rollout and Status adoption are still pending.
