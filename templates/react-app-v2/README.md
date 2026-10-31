# Development v2 application

This is an unlisted development starter using the shared React/Ant Design stack.
The matching experimental Portal and SDK are required. It does not migrate an
existing app, enroll a publisher, start a backend or grant capabilities.

## 1. Generate and inspect

The creation command below is only for a new folder; skip it when reading this
inside an already generated app. Run all commands from the Apps repository root:

```sh
python3 scripts/create-app.py APP_ID --name "My app" --template v2 \
  --parent-origin https://portal.example.invalid --publisher development-publisher
npm install
```

Replace the example parent origin with the trusted development Portal origin.
Use HTTPS, or exact loopback HTTP such as `http://127.0.0.1:31935` for a disposable
local test. Paths, credentials, query strings and noncanonical origins are refused.
`frontend/src/bootstrap.json` is immutable build configuration. Do not derive this
value from a URL parameter, referrer, arbitrary message or the parent DOM. No user
or administrator enters a backend URL during app installation.

This per-development-deployment bootstrap is provisional. Cross-deployment
trusted bootstrap/distribution must be accepted before promoting this template to
a stable public default. A local candidate is not an installable trusted release.

The app declares no required/optional capabilities and no backend. The data
compatibility declaration reserves an empty format; it creates no database or
persistent draft storage. The sample warns readers that refresh/close loses its
in-memory text. Do not describe preview as a durable save.

## 2. Develop and test

Edit `frontend/src/App.tsx` and matching keys in all three `frontend/locales` files.
`AppRoot` applies host language/theme before first visible content. `useAppPage`
declares the host title/actions; `useAppNavigation` owns signed-route requests and
`useAppDraft` supplies the standard unsaved-change hint. The sample's host Preview
action demonstrates current callback state and preserves a draft across language
updates. It renders no inner title or language selector.

Apps that declare `network.http` use `useAppNetwork` from the same root. Pass a
method, reviewed HTTPS URL and binary body; the hook owns Base64, request
correlation, cancellation and fixed errors. Never call the Portal network route,
copy the transport, supply identity fields or add arbitrary headers. The starter
keeps the capability undeclared because it has no reviewed destination.

Apps that declare `reports.read` use `useAppReports` for the current viewer's
visible reports. Call `query` for a bounded list or `get` for summary metadata and
Markdown. The hook never accepts a viewer, tenant, installation or destination;
Portal checks current session, binding and owner scope before and after each
read. The starter keeps this capability undeclared because its sample has no
report workflow.

```tsx
const reports = useAppReports();
const page = await reports.query({ date: "today", limit: 20 });
const detail = await reports.get(page.items[0].id);
```

Start automatic reads only after `reports.ready`. Handle `BridgeReportError`
codes with localized UI, abort on cleanup and do not retry `uncertain`
automatically. Render Markdown without raw HTML injection. See
[`docs/reports-v2.md`](../../docs/reports-v2.md) for the full lifecycle,
authority and failure contract.

Apps that declare `storage.files` use `useAppObjects` for bounded,
current-account data. Objects are opaque IDs with revision-checked create, list,
get, full replace and delete. The hook accepts only content and safe metadata;
Portal fixes the installation, account identity, namespace and storage route.
Use the 1 MiB per-object limit and handle `conflict`, `storage_full` and
`uncertain` explicitly. Uninstall permanently clears this data.

```tsx
const objects = useAppObjects();
const page = await objects.list("note", undefined, 20);
const note = await objects.get(page.items[0].id);
const body = new TextDecoder().decode(note.content);
```

See [`docs/objects-v2.md`](../../docs/objects-v2.md) for limits, lifecycle,
revision and failure semantics.

```sh
python3 scripts/plugin-standard.py
npm run typecheck
npm test --workspace=apps/APP_ID/frontend
```

The generated UI test runs the actual root/bridge with MessageChannels and checks
host actions, draft hints, live language, retained text and absence of a duplicate
header. It is a DOM integration test, not a browser or accessibility certificate.
Keep behavior-specific tests as the application grows.

## 3. Build an unsigned candidate

```sh
python3 scripts/build-app-v2.py APP_ID
```

The new output directory is `apps/APP_ID/.development/candidate/`:

- `frontend.zip`: compiled classic script, local stylesheet and entry/resources.
- `descriptor.json`: strict v2 descriptor with the real ZIP SHA-256.

`app.v2.json` is the source declaration. Its zero frontend digest is a build-time
placeholder; the builder never changes this source. The output descriptor is
validated by the same strict SDK parser before writing. Never sign or publish the
source placeholder. Existing output directories are refused. For another build:

```sh
python3 scripts/build-app-v2.py APP_ID --output apps/APP_ID/.development/check-2
```

The authoring packer bounds files, individual bytes and total bytes, refuses
symlinks/unsafe names, sorts entries and fixes timestamps/modes. It does not replace
host HTML/CSP validation, artifact verification, compatibility checks, signature
verification or current permission review. No CDN or external executable code is
needed by this starter.

## 4. Publication is a separate gate

Keep this app out of `index.json`. The legacy catalogue command expects `app.json`
and must not be used to convert a v2 source by renaming it. A release requires the
accepted v2 publication pipeline, exact descriptor signatures, deployment trust,
full lifecycle/browser checks and immutable app-qualified artifacts. A successful
local build grants no execution authority. Follow `docs/app-platform/` in Portal
and `docs/root-v2.md` / `docs/plugin-development-standard.md` here.
