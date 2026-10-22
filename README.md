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
python3 scripts/catalogue.py package demo-symbols
```

Build output is under ignored `dist/`; package generation is deterministic.
Shared protocol and app-specific checks are described under their own directories.
See `docs/implementation-plan.md` for the complete ordered Status implementation,
and `docs/progress.md` for actual evidence and remaining gates.

## Boundaries

Installing a ZIP executes no server code. Status monitoring requires its separate
service. The Portal owns general extension registration, current viewer/OU identity
and API mediation. Apps never obtain Portal cookies or broad administrator tokens.
An optional `/status` URL is deployment gateway configuration, not a route installed
by a ZIP. Secrets and private component data never belong in a public archive.

Source and copied reference app are provided under AGPL-3.0; see LICENSE. Independent
third-party additions must preserve applicable license notices.
