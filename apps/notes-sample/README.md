# Notes reference application

Notes is a static v2 application with no backend, container or runner
requirement. It declares required `storage.files` and stores each private note
through `useAppObjects`.

The current Portal account can create, list, open, update and delete notes. The
SDK enforces the installation namespace, account generation, quotas and
optimistic revisions. Portal backs up the data transactionally; uninstalling the
application or deleting the account permanently removes the owned objects.

## Development

```sh
npm run typecheck --workspace=apps/notes-sample/frontend
npm test --workspace=apps/notes-sample/frontend
python3 scripts/plugin-standard.py
python3 scripts/build-app-v2.py notes-sample
```

The trusted parent origin remains compiled in
`frontend/src/bootstrap.json`. Do not derive it from a query string, parent DOM,
referrer or arbitrary message.

## Ownership

This is an unlisted development reference app. It does not grant production
storage, publish a market release or approve real user migration. The matching
Portal migration `0017` and experimental SDK are required.
