# Development v2 application with a backend

An unlisted development starter: the [v2 frontend starter](../react-app-v2/README.md)
plus a Go service in its own container. The matching experimental Portal and SDK are
required. It enrolls no publisher, installs nothing and grants no capability, and a
local candidate is not an installable trusted release.

The full guide is [`docs/backend-service-v2.md`](../../docs/backend-service-v2.md): the
protocol, the sandbox, every capability and what an administrator reviews, background
tasks, outbound HTTP, reserved routes, running locally, and signing and installing.

## What is here

- `app.v2.json`: a `backend` block (one `linux/amd64` image, small resource limits),
  no required capability, optional `background.run` and `tasks.schedule`. The image is
  a placeholder reference until you build a package with `--images`.
- `service/`: the Go backend.
  - `GET /health/ready`, `POST /v1/handshake` and the viewer assertion check, through
    `packages/extensionprotocol`.
  - One example JSON route, `GET /v1/hello`, which the frontend reads with
    `useAppBackend` (`frontend/src/Backend.tsx`).
  - `POST /v1/tasks/run`, an optional background entry point that only enqueues and
    answers at once (a task execution has 45 seconds). The work runs from a small
    file-backed queue and must be idempotent.
  - `packages/proxy` starts only when the release declares `network.proxy`.
  - `Dockerfile`: static binary, user 65532, nothing writable but `/data`.
- `frontend/`: the v2 starter with a panel that calls the backend, and a test that
  runs the real root and bridge with a scripted backend.

The frontend files not listed here (build, TypeScript and test configuration) come from
`templates/react-app-v2`; `scripts/create-app.py --template v2-backend` copies that
template and then this one over it.

## Generate and check

```sh
python3 scripts/create-app.py my-app --name "My app" --template v2-backend
npm install
npm run typecheck
npm test --workspace=apps/my-app/frontend
(cd apps/my-app/service && go vet ./... && go test ./...)
python3 scripts/build-app-v2.py my-app
```

The generated Go tests, including the check that the descriptor and the code agree,
run in the generated app, not in this template directory (the placeholders are not
valid JSON). `python3 scripts/test-app-template.py` generates, checks and builds one
and is what CI runs.

## Run it

```sh
python3 scripts/run-backend-local.py my-app --build
python3 scripts/run-backend-local.py my-app --call GET /v1/hello --role admin
```

This runs the image with the same constraints as Portal's runner and signs a development
viewer assertion for you. See the guide, section "Run it locally", for what it does and
does not reproduce.

## Make it yours

1. Replace `GET /v1/hello` in `service/api.go` with your routes; verify the assertion on
   each, per request, with the exact path, query and body.
2. Replace `jobs["example"]` in `service/tasks.go`, or delete the task route and the
   `background.run` and `tasks.schedule` declarations if you need no background work.
3. Need outbound HTTPS? Add `network.proxy` to `capabilities.optional` and a
   `network_proxy.hosts` list, and call out through `newEgressClient`. Choose between
   `network.http` and `network.proxy` with guide section 8.
4. Declare only what the code uses. `service/descriptor_test.go` keeps the two aligned;
   extend it with each capability you add.
