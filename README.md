# Report Portal Apps

Shared source and distribution repository for installable Report Portal applications.
Applications have independent versions, tests, frontend archives and optional backend
images. Repository sharing does not merge their processes, databases or permissions.

| Application | State | Runtime |
| --- | --- | --- |
| demo-symbols | Existing reference app, preserved identity/version | Sandboxed frontend |
| status | In development, not in the install catalogue | Sandboxed frontend and separate service |

`index.json` is the installation catalogue. It lists only available verified assets.
The current demo entry retains its existing Portal archive URL for compatibility;
its source is preserved here. Status will be listed after its complete acceptance.
No deployment's existing market override is changed by creating this repository.

## Local checks

Use Python 3.11+ without additional packages for catalogue/packaging tools:

```sh
python3 -m unittest discover -s scripts/tests -v
python3 scripts/catalogue.py check
python3 scripts/catalogue.py check --verify-downloads
npm ci
python3 scripts/build-app-frontend.py demo-symbols
python3 scripts/catalogue.py package demo-symbols
```

Build output is under ignored `dist/`; package generation is deterministic.
Shared protocol and app-specific checks are described under their own directories.
See `docs/implementation-plan.md` for the complete ordered Status implementation,
and `docs/progress.md` for actual evidence and remaining gates.

## Marketplace publication and installation

The normal installation path is the Portal application market. A manually uploaded
development ZIP is optional for controlled acceptance; it is not a prerequisite
for normal installation. Installations still require the administrator's permission
review, and a frontend installation does not deploy or pair an independent backend.

Publish an app-qualified immutable Release before editing `index.json`. An entry
must use its exact `/releases/download/<id>/v<version>/<id>.zip` URL (the slash in
the tag may be URL-encoded). Development and snapshot versions are refused.
The existing commit-pinned demo archive remains supported at its original URL.

For an application declaring `extension.*`, commit its version-specific acceptance
record at `apps/<id>/releases/<version>.json`. The record must identify schema
version 1, the exact app ID/version and a minimum published Portal release of
v2026.43.2 or later. App-specific release workflows may require additional evidence;
Status publication retains every gate in `apps/status/releases/README.md`.

Run `python3 scripts/catalogue.py check --verify-downloads` before committing the
catalogue change. CI runs this same check. It downloads the actual bounded ZIP,
checks its manifest against source, and rejects duplicate entries, path traversal,
symlinks and oversized expanded content. For extension apps it also verifies that
the app and minimum Portal Releases are published, downloads `release.json` and
`SHA256SUMS` from the same immutable release, and binds the acceptance record,
source commit, ZIP digest and metadata digest. A missing asset or draft Release
fails the check. The offline `check` command validates local declarations only;
its success alone does not prove publication or installation.

After the canonical catalogue and real market installation path are verified,
change the Portal default URL in a separate host change. Preserve explicit DB
overrides and the legacy catalogue/archive URLs. The host currently does not
enforce a catalogue checksum field or minimum-version field: these publication
checks do not add that runtime behavior. Verify permission preview and installation
on the supported Portal release before rollout. See implementation plan section
14.2 for the migration and rollback requirements.

The retained Portal catalogue can be refreshed from this canonical source without
adding new app IDs or changing its archive paths:

```sh
python3 scripts/catalogue.py export-legacy --portal-root /absolute/path/to/StockAnalysisPrediction-Report-Portal
```

The command verifies published downloads and requires byte-identical local ZIPs.
It refuses new notification/extension capabilities, unsafe paths and concurrent
catalogue changes. Review and commit the resulting Portal JSON separately; the
command never replaces archives or expands the legacy selection. See the Portal
`docs/app-market-migration.md` runbook for configuration and rollback behavior.

## Boundaries

Installing a ZIP executes no server code. Status monitoring requires its separate
service. The Portal owns general extension registration, current viewer/OU identity
and API mediation. Apps never obtain Portal cookies or broad administrator tokens.
An optional `/status` URL is deployment gateway configuration, not a route installed
by a ZIP. Secrets and private component data never belong in a public archive.

Source and copied reference app are provided under AGPL-3.0; see LICENSE. Independent
third-party additions must preserve applicable license notices.

## Status development application

[Status](apps/status/README.md) is the first independently deployed application
under active development. Its sandbox ZIP, separate service/storage, provider
checks, OU grants, incident/outbox lifecycle and operator templates live together
under `apps/status`. It remains excluded from the production catalogue until the
[acceptance ledger](apps/status/docs/acceptance.md) and immutable release gates
are completed. The Portal platform dependency is tracked in PR #142.

## Shared plugin development standard

See [the common frontend and interaction standard](docs/plugin-development-standard.md).
Start a new unlisted application with `python3 scripts/create-app.py my-app --name "My app"`,
then run `npm install` at the repository root. Use `@portal-app/sdk`, React, TypeScript
and Ant Design for theme, locale and sandbox bridge integration. CI validates the
foundation and retains per-application security and browser acceptance gates.
