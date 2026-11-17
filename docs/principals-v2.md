# Application principal directory

`useAppPrincipals()` is the SDK entry for the reviewed `principals.read`
capability. It lets an administrator pick users and organisational units (OUs)
that may use this installation, without the app's backend having any directory
access. The frontend sends the chosen principal strings to its own backend,
which stores them as opaque values.

## Declaring it

Declare `principals.read` under `capabilities.optional`. A descriptor that lists it under
`required` is refused. Installing the app leaves the capability **off**: a Portal
administrator enables it explicitly from the installation's settings page, after reading
the disclosure ("The app's administrators can list the names of users and OUs that can use
this app."), and can withdraw it at any time. Withdrawal takes effect on the very next
directory call. A new release resets the capability to off, so the administrator reviews
it again. Until it is enabled the hook reports `available` false and calls fail with
`unsupported` or `not_permitted`; build the picker so it degrades to manual entry.

```tsx
import { useAppPrincipals } from "@portal-app/sdk/root-v2";

function OuPicker({ query }: { query: string }) {
  const directory = useAppPrincipals();
  const load = async (after?: string) => {
    const page = await directory.search({ kind: "ou", query, after });
    // page.items are { principal, label, parent }; page.next continues.
    return page;
  };
  const show = (principals: string[]) => directory.resolve(principals);
  return directory.ready ? <button onClick={() => void load()}>Search</button> : null;
}
```

- `search({ kind, query?, after?, limit? })` returns `{ items, next }`. `kind` is
  `"user"` or `"ou"`; `query` is at most 64 bytes and matches labels
  case-insensitively; `limit` is 1 to 50 (default 50). Pass the previous `next`
  as `after`; `next` is `null` when the listing is complete. OU items carry
  `parent` (an OU principal or `null`).
- `resolve(principals)` takes 1 to 100 distinct principal strings and returns
  `{ items, unknown }`. Principals the viewer cannot see are reported in
  `unknown`, never explained.
- Principals equal the `Viewer` values the same users and OUs present at launch
  and are scoped to the installation; a reinstall changes them.
- Only Portal administrators who may use the app can call the directory;
  anyone else gets `not_permitted`. Calls are rate limited per viewer
  (`busy`). The hook is unavailable (`available` false, `unsupported`) without
  the exact current grant, and the SDK admits one directory call at a time.

Errors are `BridgePrincipalError` with the stable codes `not_ready`,
`unsupported`, `invalid_request`, `busy`, `unavailable`, `uncertain` and
`not_permitted`. Result labels are display text only.
