# Application development

Follow `../../docs/plugin-development-standard.md`. Review manifest scopes before
implementing bridge calls; the template grants none. Install dependencies at the
repository root with `npm install`, then run typecheck and meaningful UI tests.
Build using `python3 scripts/build-app-frontend.py APP_ID` from the repository root.
Run package validation before requesting an immutable release. A generated app is
unlisted and does not provision a backend, credentials or viewer grants.
