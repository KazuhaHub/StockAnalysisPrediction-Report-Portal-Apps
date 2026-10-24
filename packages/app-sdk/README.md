# Shared Portal application SDK

Use this workspace package in every maintained React application. It bundles
locally into each app ZIP; it does not load scripts from Portal or a CDN.

`PortalClient(appId)` accepts requests only through the trusted parent-window
bridge. `request(method, relativePath, body)` wraps a viewer-bound independent
backend call. `directory(kind, offset)` reads that app's administrator principal
directory. `machine('GET', '/api/v1/...')` supports reviewed query-scope apps.
The host and backend remain authoritative for permissions and current identity.

The client waits for `rp:init`, matches response IDs, rejects wrong-window messages,
bounds pending requests/timeouts and discards listeners on `dispose()`. It never
reads a host session, token or browser store. Request errors have localized UI keys
and bounded HTTP status metadata, rather than untrusted upstream error text.

`PortalAppProvider` supplies Ant Design theme tokens and component localization.
`usePortalTheme` follows the trusted host snapshot. Older hosts do not supply a
locale; use `localeOf(navigator.language)` as the fallback and allow a user override.
Application forms must retain drafts across theme/locale changes and failed saves.

Read [the full standard](../../docs/plugin-development-standard.md) before adding
permissions, UI flows or publication logic. SDK usage is necessary but not sufficient
for app security or usability: each app retains its own integration/negative tests.
