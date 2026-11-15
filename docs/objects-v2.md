# Experimental application object storage

`useAppObjects()` is the development SDK client for bounded, current-account
application data. The installation must have a granted `storage.files`
capability. Objects are stored in Portal-owned tables, isolated by the
installation namespace and exact account instance; applications never receive a
database handle, filesystem path or SQL access.

```tsx
import { useAppObjects } from "@portal-app/sdk/root-v2";

const objects = useAppObjects();
const page = await objects.list("note", undefined, 20);
const note = await objects.get(page.items[0].id);
const body = new TextDecoder("utf-8", { fatal: true }).decode(note.content);
```

## API

The hook exposes stable `available`, `ready`, `list`, `get`, `create`, `update`
and `delete` methods.

- `list(collection, cursor?, limit?, signal?)` returns summaries and an optional
  next cursor. The page limit is 1..50.
- `get(id, signal?)` returns one summary plus `content: Uint8Array`.
- `create({requestId,collection,label,mediaType,content}, signal?)` returns the
  created summary. Repeating the same request ID and exact payload is
  idempotent; different content under that request ID is a conflict.
- `update(id,{expectedRevision,label,mediaType,content}, signal?)` replaces the
  full object and increments its revision.
- `delete(id, expectedRevision, signal?)` removes the object row.

Collections are lower-case ASCII letters, digits or underscores, at most 32
characters. Labels are at most 256 UTF-8 bytes without control characters.
Media types use canonical lower-case `type/subtype`. A caller cannot select the
installation, account, owner generation, namespace, database table or path.

Objects are limited to 1 MiB each. Initial admission also limits one account to
32 MiB/512 objects, one installation namespace to 256 MiB/4,096 objects, and the
whole store to 2 GiB/65,536 objects. The server enforces all limits inside the
same transaction as the mutation.

## Lifecycle and conflicts

Start automatic reads only after `objects.ready`. Ordinary language and theme
updates preserve method identity and mounted data. Unmount, channel replacement
or capability revocation rejects old closures with `not_ready`; no late response
can repopulate the new document.

Use `expectedRevision` for updates and deletes. A stale revision returns
`conflict` and never overwrites newer content. Preserve the user's draft and ask
them to reopen or explicitly replace it. A lost success response is `uncertain`;
the SDK never retries automatically.

Objects belong to the exact current account creation and generation. A recreated
username, another user, another application or an old binding cannot list or
guess the objects. Moving the same account between OUs does not share personal
objects.

Uninstall revokes application access before deleting every object, namespace
counter and byte total in the same transaction. Reinstall starts with empty
storage. Deleting an account also removes that account's objects and advances all
relevant counters. There is no retained-data adoption path in this development
scope.

## Errors

`BridgeObjectError` exposes `retryable=false` and these stable codes:
`not_ready`, `unsupported`, `invalid_request`, `busy`, `unavailable`,
`uncertain`, `conflict` and `storage_full`.

Use the code for localized UI, never `error.message`. `conflict` requires a
current read before deciding what to do. `storage_full` must not be retried until
objects are removed. `uncertain` may represent a committed mutation and is never
automatically replayed.

## Validation

Portal owns the object migration, routing, authorization and shared bridge
source. The contract generator copies and pins the bridge into this repository.

```sh
python3 scripts/generate_app_contract.py --check --apps-dir ../Portal-Apps-v2-work
npm run typecheck --workspace=@portal-app/sdk
npm test --workspace=@portal-app/sdk
npm run typecheck --workspace=apps/notes-sample/frontend
npm test --workspace=apps/notes-sample/frontend
```

The shared tests cover closed request shapes, duplicate JSON keys, the exact
1 MiB boundary, quotas, stale revisions, account isolation, cancellation,
timeouts, revocation and uninstall cleanup. The Notes application adds a real
static create/list/open/save flow. Node MessagePort tests do not replace the real
Linux browser acceptance.
