# Experimental v2 React presentation root

`@portal-app/sdk/root-v2` is an internal P06 development entry point built on the
shared `portal.app.bridge/2-dev.7` transport. It is not a released stable SDK,
accepted v2 host, capability client or migration of a maintained app. Existing
applications and the public template retain their legacy provider until the whole
host/root/package lifecycle passes acceptance. No catalogue/release changes here.

## Composition

```tsx
import { createRoot } from 'react-dom/client';
import { Button } from 'antd';
import { AppRoot, useAppPresentation } from '@portal-app/sdk/root-v2';

function Application() {
  const { presentation } = useAppPresentation();
  return <Button>{presentation.locale} / {presentation.timeZone}</Button>;
}

// An immutable trusted bootstrap value, not a query string, referrer, arbitrary
// postMessage origin, browser storage value or application-selected destination.
const portalOrigin = 'https://portal.example.invalid';
createRoot(document.getElementById('app')!).render(
  <AppRoot parentOrigin={portalOrigin}><Application /></AppRoot>,
);
```

Use exactly one root per sandbox document. The host owns the outer title, page
margins, navigation and loading cover. The root adds no outer card, border, title,
independent locale state or language selector. Ant Design components receive the
host locale and tokens directly. `useAppPresentation()` exposes only readonly
validated presentation/context: locale, timezone, document/viewport layout, theme,
installation generation and capability **hints**. Hints are not backend grants.
The private pending-commit resolver and abort machinery are not exposed through
the presentation context. The separate [own-backend hook](backend-v2.md) exposes
only the bounded, document-bound request method. Outside the root, the hook throws a fixed error.

The SDK reuses its existing `PortalAppProvider`/Ant token palette through an internal
appearance-only adapter. That adapter has no API/directory implementation and is
never given to business components. No `PortalClient` is constructed, no `rp:*`
listener is installed, and there is no v1 fallback. The legacy provider source and
released application artifacts remain unchanged. Shared visual tokens/contrast
adjustment do not fork into another application-specific implementation.

## Commit and lifecycle behavior

1. Before valid initialization, render no business subtree. The bridge checks
   exact parent Window/origin, nonces, protocol, binding and presentation shape.
2. A valid presentation schedules React state and returns a **pending Promise** to
   the bridge. Merely scheduling state is not an acknowledgement.
3. The subtree renders under the existing Ant ConfigProvider. A commit marker
   inside the application error boundary applies document `lang`, `color-scheme`,
   body background/text and resolves only from its layout effect. Promise
   continuations run after the layout-effect commit, so the host receives ready
   only after React/Ant settings and document colors are applied.
4. Initial/live locale, timezone, theme and layout settings share that path.
   Ordinary updates preserve mounted application state. Apps format dates using
   the supplied timezone; the SDK does not change JavaScript's global timezone.
5. The host's fresh challenge aborts old bridge work, clears the old subtree/context
   and increments a local mount epoch. The new generation cannot inherit prior
   form/component state. This is intentionally different from a live theme update.
6. Abort/reset/unmount rejects pending work, detaches abort callbacks and closes
   owned listeners/ports. React StrictMode mount/cleanup/remount is supported.
7. A render failure rejects pending application before acknowledgement. Transport
   failure, local render failure or aborted connection removes business content.
   The failure surface uses fixed en-US/zh-CN/zh-TW text, with no exception detail.
   Failure callbacks receive only a bounded bridge code; throwing in an observer
   cannot retain the failed subtree. A failed root does not revive on a later
   callback. Reopening creates a fresh root/session.
8. Pending render rejection can report the protocol's fixed failure before channel
   close. A render failure **after readiness** closes the local channel and shows
   the fixed local fallback; there is no new heartbeat or portable host failure
   attestation. Host-side failure/retry behavior still needs full shell integration.

Document layout has no SDK-owned viewport height or inner scroll. Viewport layout
uses the iframe viewport height and hides outer overflow; the app provides its
intended internal region. It does not resize or navigate the parent or read its
DOM. The shared root now observes natural document content height; see the
[document sizing contract](bridge-v2.md#document-sizing-extension). The boolean draft guard described below is available; registered navigation with typed queries is described below; draft persistence
remains separate P06 work.

## Refresh and white-frame boundary

This root applies settings before ready, but JavaScript cannot retroactively
remove a browser's initial unstyled document paint. A compliant Portal host must
keep the iframe hidden/covered with the **host's current theme** from creation and
on every load/reset until the latest presentation acknowledgement. Do not reveal
on iframe `load`, React scheduling or initial HTML delivery alone. Do not weaken
sandbox/CSP, infer theme from host DOM or inject arbitrary app HTML to hide a flash.

Real-browser refresh, dark/light transition and scrollbar/layout checks remain
required when the v2 host is wired. jsdom/MessagePort tests prove commit ordering
and lifecycle behavior, not rendered pixels or absence of every white frame.
There is no claim that deployed Status appearance has changed in this PR.

## Checks

Tests were written first and failed on the missing root import. SDK tests cover
pre-init gating, commit-before-ack, Ant locale/tokens, ordinary state preservation,
abort/reset/failure cleanup, sanitized error output, failure finality and unmount.
An additional integration test uses the **real shared host/client** and transferable
Node MessagePorts with explicit window/source/origin fixtures: the host's initial
ready observer checks the committed DOM, live updates preserve a stateful button,
and a fresh host generation resets its state. StrictMode is included. These are
in-process protocol tests, not browser or server authority evidence.

Run from the monorepo root:

```sh
npm run test:sdk
npm run typecheck
python3 scripts/generate_app_contract.py --check
python3 scripts/plugin-standard.py
python3 scripts/test-app-root-v2.py
python3 scripts/test-app-template.py
npm test --workspace=portal-symbols-demo
npm run test:status-ui
python3 scripts/build-status-frontend.py
git diff --exit-code -- apps/status/service/internal/status/public
```

The root build fixture is development-only under SDK tests. Its origin is reserved
`.invalid`, it has no catalogue entry or release, and `test-app-root-v2.py` builds
in an exclusive temporary directory then checks exactly one classic IIFE script
and one local stylesheet. It needs no CDN, remote font, ESM fetch, storage token or
new permission. The existing CI runs that build check with the frontend standard
suite. Existing template, demo and Status checks verify the unchanged legacy
consumers alongside the new experimental entry point.

The own-backend integration case also uses the real React root and transferable
MessagePort host/client under StrictMode. An initial automatic GET starts only
after ready, a locale update preserves data without repeating that GET, and an
explicit button action performs one POST. The dispatcher is a test callback,
not a native backend or production authority proof. The SDK suite now has 192
passing local tests with workspace typechecks. The preceding functional commit
`fef8ef7a4efd2da1aca96a4960dffaf6985bea85` passed complete check run 40843217337;
this additional test still requires CI at its own commit.


## Unsaved changes

Use `useAppDraft(dirty)` from `@portal-app/sdk/root-v2` in each mounted form.
The root combines all registered forms with logical OR. Saving one form does not
clear another form's changes. Unmounting a form removes its own bit. Language and
theme updates preserve the registry. A new document/connection gets a fresh
registry. StrictMode cleanup/remount does not leave an abandoned owner behind.

```tsx
function Editor() {
  const [value, setValue] = useState('');
  const [saved, setSaved] = useState('');
  useAppDraft(value !== saved);
  return <Input value={value} onChange={event => setValue(event.target.value)} />;
  // After a successful save, setSaved(value). Do not clear on a failed save.
}
```

Import `useState` from React, `Input` from Ant Design and `useAppDraft` from the
root entry point. The example omits persistence deliberately: the hook reports a
boolean only. It does not save text, restore drafts, intercept app-local form
navigation, call an app-provided confirmation handler or grant backend access.

After readiness, the SDK sends the aggregate bit over the current private bridge.
Updates are coalesced to at most ten messages per second; duplicate bits are
suppressed. Before readiness the registry keeps its current aggregate and emits
it when ready. Retirement cancels queued reports. Avoid app-specific window
`beforeunload` handlers or custom host confirmation dialogs.

The Portal host owns the localized Ant confirmation for routed departures,
including its return link and browser history. Cancel keeps the document mounted;
confirm proceeds without waiting for an app callback. Refresh/close uses the
browser's native warning, whose text and availability are browser controlled.
Only routed departures are guarded: document crashes, direct iframe reloads,
forced termination, session loss and unsaved state not reported by the app can
still lose data. Implement appropriate persistence separately.


## Registered navigation

`useAppNavigation()` exposes `ready`, the host-committed `path`, readonly signed
`routes` and `navigate(path, {replace, query} = {})`. Render route-specific business
content from `path`. The root does not construct an inner browser router and apps
must not read or change parent DOM/history. Changing the route preserves the
same root/document and state in components that remain mounted. A layout change
between signed document/viewport routes does not reload the application.

```tsx
const navigation = useAppNavigation();
return <Button disabled={!navigation.ready}
  onClick={() => navigation.navigate('/editor')}>Open editor</Button>;
```

The path must exactly equal a route in the package's signed descriptor. Routes
are limited to 32, with unique IDs/paths and one `/` home route. No arbitrary URL, dot traversal, undeclared query, fragment, dynamic route
template or inferred permission is accepted. Query names and constraints must
be declared in the signed descriptor as described below. Do not put credentials or tokens in route state.

The return boolean means a request was sent or the path is already current; it
is **not** a committed-navigation result. The host may decline it while another
confirmation is open, while applying a newer presentation, or when it is stale.
The committed path changes only through a later host presentation update. Cancel
keeps the old path. There is no background retry/queued navigation and no app veto
after user confirmation. Requests faster than one per 100 ms return false locally;
the host rejects a channel above twenty increasing requests per second.

Deep links and host browser history use the same registered path/layout. Invalid
or undeclared deep links never mount executable content. Back/forward does not
repeat launch requests, recreate the iframe or replay a backend write. Persistent drafts and full shell metadata/actions remain separate work. The SDK and host must use the matched development protocol.


## Typed route queries

Each route can declare up to 16 query fields. No declaration means no permitted
query fields. Supported variants are exact and do not mix constraints:

```json
"query": [
  {"name":"page", "type":"integer", "min":0, "max":100},
  {"name":"q", "type":"text", "max_bytes":64},
  {"name":"active", "type":"boolean"},
  {"name":"sort", "type":"enum", "values":["newest","oldest"]}
]
```

Names are unique lowercase ASCII identifiers (letters/digits/underscores, max 32;
constructor/prototype are reserved). Integer bounds lie within +/-1000000000 and
min<=max; text max_bytes is 1..256 UTF-8 bytes; enums contain 1..16 unique bounded
ASCII codes. Every query field is optional in a URL, allowing the app to choose
its normal default when absent. Explicit false, zero and empty text are retained.
There is no arbitrary regex, nested object, array-valued parameter or implicit
string-to-number conversion in SDK requests.

```tsx
const navigation = useAppNavigation();
const page = typeof navigation.query.page === 'number' ? navigation.query.page : 0;
navigation.navigate(navigation.path ?? '/', {
  query: {...navigation.query, page: page + 1},
  replace: true,
});
```

`query` is a readonly typed view of the host-committed search. `search` is its
canonical encoded string. The typed query object retains its identity across
locale/theme updates when its definition and search are unchanged, so query-based
data effects do not rerun for appearance alone. Never update a form from the send boolean; canceled
navigation keeps the previous committed query. Omit query (or supply {}) to clear
it. Sending replaces the full query set; spread the current query to preserve
other filters. The experimental API now uses an options object rather than a
positional replace boolean, and requires the matched dev.6 host/SDK.

Canonical search sorts names, encodes with URLSearchParams and uses exact decimal
integers and true/false boolean strings. Duplicate names, unknown fields, wrong
types, out-of-range values, noncanonical encodings/order, controls, malformed
Unicode and excess bytes are refused. The total encoded search is capped at 2048
ASCII bytes independently of each text limit. Typed rules and pure validators
are source-pinned into this SDK from Portal, including mirrored tests.

Queries are address/history state, not a secret or draft storage mechanism.
Declared state does not grant access: backend operations still use current server
authorization. No database layout or legacy app protocol is changed by this step.


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
