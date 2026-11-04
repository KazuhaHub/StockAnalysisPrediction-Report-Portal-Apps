# Shared Portal application SDK

Use this workspace package in every maintained React application. It bundles
locally into each app ZIP; it does not load scripts from Portal or a CDN.

The experimental `@portal-app/sdk/descriptor-v2` subpath validates v2 descriptor
declarations against the shared Go/TypeScript corpus. It grants no authority and
does not verify signatures, artifacts or compatibility. See
[the contract limits and verification guide](../../docs/descriptor-v2.md).

`PortalClient(appId)` accepts requests only through the trusted parent-window
bridge. `request(method, relativePath, body)` wraps a viewer-bound independent
backend call. `directory(kind, offset)` reads that app's administrator principal
directory. `machine('GET', '/api/v1/...')` supports reviewed query-scope apps.
The host and backend remain authoritative for permissions and current identity.

The client waits for `rp:init`, matches response IDs, rejects wrong-window messages,
bounds pending requests/timeouts and discards listeners on `dispose()`.
It disposes automatically on a real page exit, retaining the bridge during browser
back/forward-cache suspension so returning to a cached page remains usable. It never
reads a host session, token or browser store. Request errors have localized UI keys
and bounded HTTP status metadata, rather than untrusted upstream error text.

`PortalAppProvider` supplies Ant Design theme tokens and component localization.
`usePortalTheme` follows the trusted host snapshot. `usePortalLocale` follows the
panel by default, falls back to browser language on older hosts and supports an
explicit override that can return to following the panel. Use `PortalLocaleSelect`
for that optional control rather than keeping another locale state machine.
Application forms must retain drafts across theme/locale changes and failed saves.

SDK 0.2 also supplies `PortalPage`, `PortalState`, `PortalErrorBoundary`, labelled
text/number/choice/checkbox fields and `usePortalResource`. The shared CSS owns
page spacing, typography and narrow-control reflow. Status, the maintained demo
and the generator use this foundation. See the
[API and ownership contract](../../docs/sdk-foundation.md) for signatures,
examples, error/retry behavior and review/acceptance boundaries.

Read [the full standard](../../docs/plugin-development-standard.md) before adding
permissions, UI flows or publication logic. SDK usage is necessary but not sufficient
for app security or usability: each app retains its own integration/negative tests.

## Experimental v2 React root

`@portal-app/sdk/root-v2` supplies `AppRoot`, `useAppPresentation`,
`useAppBackend`, `useAppNetwork`, `useAppReports` and `useAppObjects` for isolated v2 host
development. It applies host locale/theme/timezone through React/Ant and
acknowledges only after layout commit. Request hooks expose only capabilities
and channels advertised by the current host connection; they grant no authority.
Read
[the root contract](../../docs/root-v2.md),
[own-backend client](../../docs/backend-v2.md), and
[reviewed network client](../../docs/network-v2.md) and
[current-viewer reports client](../../docs/reports-v2.md) and
[application object client](../../docs/objects-v2.md) for boundaries and tests.
