# Portal application development standard

This standard applies to every maintained application in this monorepo. React,
TypeScript and Ant Design are the common frontend stack, matching Portal's pinned
major versions. Independent plugins must look and behave like part of the Portal
without accessing its DOM, cookies, credentials or private APIs. A static ZIP can
bundle this stack completely; sandbox isolation does not require handwritten DOM UI.

## Shared frontend foundation

The [experimental v2 presentation transport](bridge-v2.md) belongs to the shared
SDK/root integration. The [experimental React root](root-v2.md) implements
commit-aware presentation for isolated v2 development. An explicit
[development v2 template](../templates/react-app-v2/README.md) now exercises this
root; it is not the stable public default or a migration of published apps. Maintained business apps must not implement their own
handshake or HTTP transport. Experimental v2 backend calls use
[`useAppBackend`](backend-v2.md), while reviewed outbound HTTP uses
[`useAppNetwork`](network-v2.md). Current viewer reports use
[`useAppReports`](reports-v2.md). Current viewer authority remains with the
Portal host. Do not use this development entry point to bypass the legacy
provider before v2 host/root acceptance.

Experimental v2 package declarations use the [shared descriptor source and
generation workflow](descriptor-v2.md#shared-source-contract). Do not duplicate
capability enums, edit generated products or substitute editor schema validation
for strict parsing and admission. Existing releases still use their legacy format
until the v2 platform is accepted and released.

The executable presentation foundation is SDK 0.2. Existing legacy applications use
`PortalAppProvider`, `PortalPage` and `usePortalLocale`; declaring the SDK as a
dependency alone is insufficient. The checked template and both maintained
consumers demonstrate the same composition. Read the
[SDK API and ownership contract](sdk-foundation.md) before creating another
layout, language state machine, field wrapper or request-state hook.

- Use `@portal-app/sdk` for parent-window identity checks, scoped request/reply
  handling, timeouts, theme snapshots and supported locales. Do not copy a bridge
  implementation into a plugin or call session-authenticated admin endpoints.
- Use React 19.3, Ant Design 6.6 and TypeScript 7, pinned in the workspace lockfile.
  Upgrade shared versions deliberately against Portal compatibility checks rather
  than allowing individual plugins to select unrelated UI frameworks or versions.
- Build a self-contained classic IIFE, local CSS and static entry document.
  Do not depend on CDN scripts, remote fonts, ESM fetches from an opaque origin,
  inline scripts, shared localStorage or dynamically fetched executable code.
- Retain `sandbox="allow-scripts"`. No `allow-same-origin`, `allow-forms`, host DOM
  injection, broad null-origin CORS, tokens in browser storage or weakened Portal CSP.
- Theme through `ConfigProvider` and the SDK's trusted Portal color/radius snapshot.
  Verify primary button text contrast in normal, hover and active states.
  Use Ant Design typography, spacing, buttons, fields, validation, drawers, tables,
  alerts and loading states. Custom CSS is for layout and app-specific visualization.
- Language resources cover en-US, zh-CN and zh-TW with identical keys. Prefer an
  optional trusted host locale; fall back to browser locale on older Portal versions.
  Runtime locale changes must preserve unsaved form drafts.
  `usePortalLocale` owns the default-follow/explicit-override behavior. If an app
  needs a language selector, use `PortalLocaleSelect`, including its return-to-panel
  option. Do not initialize a separate language state only once on mount.
  The host's optional top-level `locale` travels on `rp:init` and `rp:theme`;
  a host update supplying this field does not require an app-specific host hook.

Use `PortalPage` for the initial/private application surface: one labelled main
region, a level-three title, optional description and a wrapping action area.
The SDK supplies the 1200-pixel content bound, 24-pixel desktop padding,
16-by-12-pixel narrow padding, system typography and control sizing/reflow fixes.
Applications supply business content and visualization layout, rather than
redeclaring page, body or typography defaults. Do not add a second Portal header,
account menu or global navigation inside the iframe.

Use shared `PortalTextField`, `PortalNumberField`, `PortalChoice` and `PortalCheck`
for ordinary configuration fields; they preserve real labels, unique IDs and
consistent widths. Secret fields have no reveal toggle and use new-password
autocompletion. These controls never persist secrets; backend sealing remains
the service's responsibility. Business-specific controls may compose Ant Design
components when they have their own accessibility/behavior tests.

Use `PortalState` for standalone loading, empty, forbidden, incompatible and
recoverable-error surfaces. Provider render failures use a bounded localized
`PortalErrorBoundary` fallback without printing exception contents. The boundary
does not retry a failed write. `usePortalResource` ignores obsolete async replies
and clears data on a failed current load; applications still own authority checks,
freshness semantics and safe error dictionaries.

## Development v2 authoring

Generate an unlisted development app explicitly:

```sh
python3 scripts/create-app.py my-app --name "My app" --template v2 \
  --parent-origin https://portal.example.invalid --publisher development-publisher
npm install
python3 scripts/plugin-standard.py
npm run typecheck
npm test --workspace=apps/my-app/frontend
python3 scripts/build-app-v2.py my-app
```

Choose the trusted development Portal origin, never a real credential. HTTPS or
canonical loopback HTTP is accepted. This origin is compiled from immutable
bootstrap configuration; it is not inferred from the parent DOM, referrer, query
or arbitrary message. Cross-deployment distribution bootstrap remains a release
gate before promoting this provisional template to the public default.

| Area | Legacy published composition | Experimental v2 composition |
| --- | --- | --- |
| Manifest | `app.json` | `app.v2.json` source, generated `descriptor.json` |
| Root | PortalClient + PortalAppProvider | AppRoot with immutable trusted bootstrap |
| Page | PortalPage inside document | useAppPage rendered by Portal |
| Locale | usePortalLocale compatibility behavior | useAppPresentation; follows committed Portal locale |
| Navigation | Legacy host APIs | useAppNavigation with signed routes |
| Draft | App-specific persistence/legacy behavior | useAppDraft hint; persistence is separate |
| Frontend build | build-app-frontend.py + legacy catalogue tooling | build-app-v2.py, unsigned local candidate only |

A v2 app must not mount PortalPage/PortalAppProvider/PortalClient or expose an
independent language selector. AppRoot already supplies the shared Ant foundation.
Use shared field/typography components for content, and the root-v2 hooks for
presentation, navigation, current-viewer reports, own-backend calls and page
ownership. The checker
requires the v2 entry points, rejects dual manifests/copied authority and verifies
immutable origin configuration. It remains a structural check, not a JS security
proof or complete UX acceptance.

The generated sample uses a host Preview action and a labelled textarea. It
retains text across route/language updates and uses the shared dirty-navigation
hint. It clearly reports that its data is in memory only. A preview is not a save.
Do not add persistent-storage claims until a granted broker/service operation
actually commits them.

The source descriptor has a zero frontend-digest placeholder. The v2 builder
validates exact source bytes with the strict SDK parser, rebuilds local assets,
creates a bounded deterministic ZIP and validates a new descriptor with its real
SHA-256. It preserves the source and refuses existing output directories. Use
`--output` with a new local directory for each subsequent candidate. Outputs are
unsigned and unlisted; no signing, publisher trust, upload, market modification,
backend provisioning or execution approval happens during this command.

The source/parser/ZIP checks do not replace host HTML/CSP, signature,
compatibility, resource and current permission admission. A managed declaration
still needs independently verified immutable backend artifacts and lifecycle
acceptance. Never rename a v2 source into legacy app.json to bypass those gates.
Follow the [step-by-step template guide](../templates/react-app-v2/README.md).

## Interaction and information architecture

The initial page answers the reader's main question. For Status this is current
service availability, rather than internal identifiers, configuration records or
notification queue details. A backend outage, stale sample or absent permission
must never be styled as a healthy result.

Keep operator configuration behind an administrator entry. Create/edit flows use
focused drawers or dialogs and progressive steps. Basic setup shows only the fields
needed for the selected check type. Advanced timeouts, network exceptions and
transport details are explicitly expandable. Current defaults are explained near
their controls. Do not present every database field as a compulsory configuration.

Keep read visibility, financial visibility and anonymous publication distinct.
Administrator-only is the initial policy. Explain the effect of a grant before
saving it. Never infer notification recipients from read grants.

Use stable loading, empty, forbidden, unavailable, conflict and validation states.
Preserve drafts and focus after failed requests. Prevent duplicate writes, perform
keyboard actions without native sandbox form submission, and refresh idle views
without replacing focused inputs or active forms. Confirm destructive actions with
their actual effect; keep independent controls independent (for example, resuming
probes must not implicitly resume notification delivery).

## Application and backend boundaries

Each app owns `apps/<id>/app.json`, its frontend workspace, tests and documentation.
An optional backend owns its independent runtime, storage, keys and lifecycle.
Installing a ZIP does not silently start a process or grant provider credentials.
Use the documented viewer-bound extension API for private backends. Recheck current
account/OU/installation authority on the server, filter before counts/pagination and
use explicit public DTOs. A frontend permission check is only a presentation aid.

Configuration belongs in app-managed storage and the UI. Infrastructure/key sources
may use deployment configuration. DB shape changes still require owner approval;
this frontend standard does not authorize any schema change or host business patch.

## Required repository artifacts and checks

Generate an unlisted app with `python3 scripts/create-app.py my-app --name "My app"`.
Run `npm install` at the repository root, review the zero-scope manifest and add
behavior-specific UI tests before publication. Build with
`python3 scripts/build-app-frontend.py my-app`; this creates only local static assets.

New apps start from the shared React/Ant Design template, including the SDK, strict
TypeScript config, deterministic IIFE build, three locales and meaningful UI tests.
Every frontend declares the SDK/React/Ant Design dependencies and participates in
the root workspaces/lockfile. The standards validator refuses missing foundations.

CI runs dependency installation from the lockfile, standards validation, typecheck,
SDK and app UI tests, locale parity, package validation and browser integration.
Integration checks retain sandbox isolation, theme/locale changes, current viewer
authority, error/draft handling, keyboard navigation, narrow layouts, accessibility
and installation lifecycle. Tests must follow the intended user flow; do not retain
a simpler hidden test-only UI or weaken a gate to make a rewrite pass.

The foundation validator checks dependencies, required common entry points, locale
parity and forbidden copied authority/bridge access. These structural checks are
not a JavaScript security proof or a visual acceptance certificate. The generated
template is also compiled and exercised, SDK behavior tests cover stale replies,
parent-only locale updates and bounded failure UI, and the Status browser suite
exercises the actual composition. Reviewers must still inspect the application
flow and business-specific controls.

Published versions remain immutable. Migrate maintained source and publish a new
app-qualified release; never overwrite an older ZIP/image to retrofit this standard.
The existing demo and Status are migration targets, not examples that authorize new
exceptions. A release must disclose any unfinished migration or acceptance work.

## Working example and review checklist

A generated workspace has this structure:

```text
apps/my-app/
  app.json                    # Identity, version, entry and requested scopes
  README.md                   # Setup, supported Portal version and lifecycle
  frontend/
    package.json              # Shared pinned dependencies and scripts
    tsconfig.json             # Strict TypeScript, including unused checks
    vite.config.ts            # Local classic-script bundle
    locales/{en-US,zh-CN,zh-TW}.json
    src/{main.tsx,App.tsx,index.html,style.css}
    tests/{app.test.tsx,setup.ts}
```

From the repository root:

```sh
python3 scripts/create-app.py my-app --name "My app"
npm install
python3 scripts/plugin-standard.py
npm run typecheck
npm test --workspace=apps/my-app/frontend
python3 scripts/build-app-frontend.py my-app
python3 scripts/catalogue.py package my-app
```

The generator refuses existing directories and invalid IDs. It does not edit the
catalogue, deploy a backend or grant permissions. Packaging a compiled workspace
without `frontend/dist` fails; source files are never a substitute for a build.
CI also generates a disposable app and actually typechecks, tests and builds it,
so the documented starting point is exercised rather than only inspected.

For a reviewed query-scope application, use
`client.machine('GET', '/api/v1/symbols?limit=20')`. For an independent backend,
use `client.request('GET', '/v1/components')`; the SDK wraps the app-bound extension
route. Grant only the matching manifest scopes and verify denial without them.
Call `client.dispose()` when the app is destroyed. Components never construct a
Bearer token, read Portal cookies or issue their own parent-window bridge messages.
Anonymous public pages may read only their explicit public projections with
`credentials: 'omit'`; they use the same React/Ant Design dependencies and locales,
without a private bridge or an authenticated-client fallback.

Before review, provide the problem and resulting reader/operator flow, permission
and data impact, validation evidence and rollout/rollback instructions. Include
screens for empty/loading/error states, narrow layouts and both themes where
relevant. Verify a failed save retains the draft and its error is visible inside
the active dialog. Review secrets, exports, publication and notification recipients
separately from ordinary component visibility.

The Status publisher requires the `frontend-standard` job in addition to the full
service/browser/artifact matrix; an older successful job set cannot bypass it.

Before publication, select a new app version, review its app-specific acceptance
record and run the guarded release workflow against the exact accepted main commit.
Source migrations can be reviewed before a release version is selected; such local
builds are development candidates and must never replace an existing public ZIP.
Update the market only after immutable assets and compatible Portal downloads are
verified. Upgrade through the market, preserve independent storage and keys, and
check current installation identity and backend pairing before resuming operations.

For experimental v2 host cards/titles, provide the signed
[`presentation.display` metadata](descriptor-v2.md#signed-host-display-metadata)
in all three panel languages. Choose its icon from the shared Ant vocabulary;
never replace the host name with HTML or an external icon URL. This provisional
extension does not publish or convert the existing legacy applications.
