# SDK foundation and application ownership

The common package is `@portal-app/sdk` 0.2. It is bundled into each immutable
application ZIP; Portal never executes it in its own React tree. Its purpose is
consistent presentation and integration, not a second application framework or
permission authority. React, TypeScript and Ant Design remain pinned centrally.

## Start with the shared composition

```tsx
import {
  PortalAppProvider, PortalClient, PortalPage, PortalState,
  PortalLocaleSelect, usePortalLocale,
} from '@portal-app/sdk';

const client = new PortalClient('my-app');

export function Application() {
  const language = usePortalLocale(client);
  const copy = dictionaries[language.locale];
  return <PortalAppProvider client={client} locale={language.locale}>
    <PortalPage title={copy.title} description={copy.description} actions={
      <PortalLocaleSelect locale={language.locale} selection={language.selection}
        onChange={language.setSelection} />
    }>
      <PortalState kind="empty" title={copy.empty} />
    </PortalPage>
  </PortalAppProvider>;
}
```

`dictionaries` is the application's typed en-US/zh-CN/zh-TW resource mapping.
The generated template has a complete runnable version. A language selector is
optional; follow-panel remains the default even when no selector is shown.
Do not construct a new client on every render. The client owns real page-exit
cleanup and preserves a browser back/forward-cache suspension. A separately owned
client may be explicitly disposed when its true owner is destroyed.

## API and responsibility matrix

| Capability | SDK contract | Application/service responsibility |
| --- | --- | --- |
| `PortalClient.request` | App-bound relative extension request, parent-window validation, bounded pending work, timeout and response matching | Review manifest scopes, declare the backend route policy, authorize current viewer and component access on the server |
| `PortalClient.directory` | Administrator principal directory for this installation | Explain the scope of read/finance grants before saving; do not infer notification recipients |
| `PortalClient.machine` | Reviewed query-scope GET call through the host | Request only the capabilities actually needed; no private session endpoints |
| `usePortalTheme` | Trusted theme snapshot and live subscription | Custom chart contrast and semantics; never read parent DOM or browser storage |
| `usePortalLocale` | `{ locale, selection, setSelection }`; `selection` starts as `panel`; host updates apply live; explicit choices remain until `panel` is selected again | Supply matching dictionary keys and retain drafts across language changes |
| `PortalLocaleSelect` | Localized language labels and a visible follow-panel option | Include it only when an explicit override is useful; no separate custom selector |
| `PortalAppProvider` | Ant Design theme/locale, document language/color scheme/surface and localized render-failure boundary | Wrap the whole maintained app once; public websites use public-only data and never add an authenticated bridge fallback |
| `PortalPage` | Labelled main region, title, description, wrapping actions and responsive content spacing | Reader-first content, administrator entry, app-specific sections/charts |
| `PortalState` | Explicit loading/empty/error/forbidden/incompatible presentation; bounded retry action when supplied | Select truthful state, localized explanatory text and a safe read retry; never display a backend outage as healthy |
| `PortalErrorBoundary` | Bounded localized render-failure fallback; exception contents are not displayed | Prevent writes in render/effects; diagnose errors without logging secrets |
| `PortalTextField` | Label/ID binding, plain/multiline/secret input and contextual help | Validation rules, secret lifecycle and service-side encryption |
| `PortalNumberField` | Labelled integer input with supplied min/max | Domain bounds and authoritative server validation |
| `PortalChoice` | Labelled single/multiple selection, searchable option labels and disabled state | Current authorized options and meaningful empty/loading feedback |
| `PortalCheck` | Labelled checkbox with controlled state | Explain consequences; keep independent operations independent |
| `usePortalResource` | `{ data, loading, errorKey }`; obsolete/unmounted responses are ignored and a failed current load clears data to its initial value | Memoize the loader, translate safe error keys, choose refresh cadence and freshness behavior |

The resource hook suppresses obsolete results; it does not cancel an in-flight
server operation. Changing locale must not create another paid operation or
replay a write. Keep form drafts in their existing component and initiate writes
only from deliberate user actions. Disable duplicate submissions and render the
error inside the active dialog. Status retains its tested action guard and
step editor; these are domain behavior rather than a universal workflow engine.

## Presentation rules with examples

- A monitoring app starts with service state; a report app starts with report
  coverage. Internal IDs, queues and transport flags belong in detail/management.
- Use the shared title/action shell, then ordinary Ant Design Cards, Table, Tabs,
  Drawer and Steps. A different business chart is allowed; a competing global
  header, component library or manually styled form system is not.
- Keep advanced network/timeout fields collapsed. For long setup, show the next
  required step rather than every service field at once. Use backend validation
  as the authority and preserve inputs when it refuses a save.
- Show loading, empty, forbidden, unavailable and incompatible states distinctly.
  Do not render hidden rows or reveal forbidden counts while waiting for authority.
- Use localized visible text and real labels. Test keyboard order, dialog focus,
  narrow layouts, enlarged text, long labels and both themes. Automated scans are
  evidence for tested rules, not a claim of full screen-reader certification.
- Public pages never receive private DTOs, credentials, current OU data or an
  authenticated fallback. They may reuse presentation components without creating
  a Portal client. A public/private mode change remains an explicit operator choice.

## Adding a common capability

First identify actual duplicated behavior in two consumers, or a missing safety
contract reproducible in the template. Write a failing behavior test, add the
smallest public API and document its ownership boundary. Update the template and
affected consumers in the same change. Do not add application-specific endpoints,
notification recipients, schemas or provider credentials to the SDK.

Run workspace typechecks, SDK tests, both maintained consumers, generated-template
typecheck/test/build, foundation validation and Python packaging tests. Shared
presentation changes also run the installed Status browser/accessibility suite.
Keep the catalogue pinned to verified existing releases until a new app-qualified
release is published and downloaded successfully. Source adoption does not change
already installed ZIP bytes; publish a new version rather than rewriting Beta.3.

## Intentionally outside the SDK

No arbitrary SQL, model execution, SMTP/Slack client, host shell, Docker socket,
database migration, credential vault, inferred OU policy or silent permission
grant belongs here. Services use their own approved storage and current authority.
Portal supplies only reviewed generic capabilities. A registry of business-specific
pages or mandatory global state library is not required to achieve consistent UI.
