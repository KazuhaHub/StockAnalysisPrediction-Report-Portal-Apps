# Application repository rules

- Keep all installable application sources in `apps/<id>`. Each app owns its version,
  tests, frontend ZIP and optional independently deployed backend.
- Portal integrations use documented sandbox bridge capabilities. Never access its
  session cookie, host DOM, private database or administrator endpoints from apps.
- Never attribute artifacts or commits to tools or agents. No attribution trailers.
- Developer-facing text is English. UI strings use en-US, zh-CN and zh-TW locales.
- Ask the owner before writing any database shape change. Approved schemas and
  restore/deletion rules must be linked from each app's storage documentation.
- Write meaningful failing tests before behavior changes. Run affected app checks;
  shared tooling/protocol changes require every affected consumer's checks.
- Feature configuration belongs in app-managed storage/UI. Bootstrap configuration
  contains only infrastructure and key sources. Never commit real credentials.
- Publish app-qualified immutable versions. Do not publish unfinished apps in the
  root catalogue, mutate an existing release or change the Portal default market
  until the new catalogue and artifacts are verified.
