# Experimental v2 React presentation root

`@portal-app/sdk/root-v2` is an internal P06 development entry point built on the
shared `portal.app.bridge/2-dev.2` transport. It is not a released stable SDK,
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
DOM. Automatic content sizing, guarded navigation and draft persistence are
separate remaining P06 contracts.

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
