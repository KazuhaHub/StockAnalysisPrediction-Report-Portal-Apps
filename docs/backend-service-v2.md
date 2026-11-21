# Writing a v2 backend service

This guide is for writing the container behind a v2 app: the Go service that
answers the app's frontend, runs background work and, when an administrator
allows it, reaches the network. The frontend side is
[backend-v2.md](backend-v2.md) (`useAppBackend`). Reference implementations are
[`apps/kazuha-hub-market-monitor/service`](../apps/kazuha-hub-market-monitor/service) (the first real
backend app: a Go wrapper around a Python pipeline) and
[`apps/scheduled-digest/service`](../apps/scheduled-digest/service) (a neutral
fixture).

Portal's own documents are the source of truth for every contract below. They
are the `docs/app-platform/` directory of the Portal repository, linked as
"Portal doc NNN" (the numbers are the file prefixes). Everything here is
development software: the formats carry `-dev` versions, and a section named
"Not yet available" says what does not exist, so nothing in this guide is a
promise.

## 1. Start from the template

```sh
python3 scripts/create-app.py my-app --name "My app" --template v2-backend \
  --parent-origin http://127.0.0.1:31935 --publisher development-publisher
npm install
```

`--parent-origin` is the origin of the Portal that will host the app, compiled
into the frontend (see [section 11](#11-build-sign-install)). The command adds
`apps/my-app` with the v2 frontend (`frontend/`), an `app.v2.json` with a
`backend` block, and the service:

| File in `apps/my-app/service/` | What it is | Edit it? |
| --- | --- | --- |
| `platform.go` | Registration, boot handshake, viewer assertion and service-identity checks | Rarely: shared plumbing |
| `api.go` | Routes: readiness, handshake, one example viewer route (`GET /v1/hello`), the task entry point | Yes: add routes here |
| `tasks.go` | A small file-backed queue; `jobs` lists what a task may do | Yes: replace the example job |
| `egress.go` | Opt-in forwarder start and an HTTPS client for reviewed hosts | Only if you declare `network.proxy` |
| `main.go` | Socket, boot ID, shutdown | Rarely |
| `Dockerfile` | Static, non-root, nothing writable but `/data` | Rarely |
| `*_test.go` | Protocol, task and descriptor-consistency tests | Extend them |

Check it, from the repository root:

```sh
python3 scripts/plugin-standard.py
npm run typecheck
npm test --workspace=apps/my-app/frontend
(cd apps/my-app/service && go vet ./... && go test ./...)
python3 scripts/build-app-v2.py my-app          # unsigned candidate
```

`python3 scripts/test-app-template.py` does the same for a freshly generated
app and is what CI runs. CI builds no image.

## 2. The protocol: `portal.backend/1`

The container has no network address. Portal's runner talks to it over a Unix
socket, `PORTAL_APP_HTTP_SOCKET` (`/run/portal-app/http/app.sock`), speaking
plain HTTP/1.1 with JSON bodies. A second directory,
`/run/portal-app/broker`, is mounted read-only and holds
`registration.json`; its `broker.sock` is the channel back to the runner
(section 7). Nothing else enters or leaves the container.

| Route | Caller | Identity | Purpose |
| --- | --- | --- | --- |
| `GET /health/ready` | runner | none | Answer `{"protocol":"portal.backend/1","ready":true,"data_format":"1"}` once serving. No query string. |
| `POST /v1/handshake` | runner, at every start | proves the registration key | `{"challenge":...}` in, `{"answer":...}` out. The answer carries the backend's boot ID. |
| `GET/POST/PUT/DELETE /v1/...` | a viewer, relayed | viewer assertion (`X-Portal-Assertion`) | Your routes. |
| `POST /v1/tasks/run` | Portal's task worker | service identity (`X-Portal-Service-Identity`) | Background work (section 6). |
| `/v1/public/`, `/v1/ingress/`, `/v1/machine/` | reserved | their own assertion | Section 9. |

**Registration.** `registration.json` holds the installation identity and a
32-byte signing key that only Portal's runner and this backend share. The file
must be canonical (the backend re-marshals what it read and refuses a
difference), the key's SHA-256 must equal the key ID, and it can change under a
running backend, so `platform.go` reloads it per request rather than caching it.
Never log it or copy it out of the container.

**Boot ID and handshake.** At each start `main.go` draws a random boot ID. Portal
sends a challenge signed with the registration key; the backend answers with the
boot ID signed the same way. Only then does Portal issue viewer assertions, and
every assertion is bound to that boot ID, so an assertion for an earlier process
is refused.

**Viewer assertion.** Portal's relay signs the current viewer into every request
it forwards: an HMAC-SHA256 token (`base64url(JSON).base64url(MAC)`) in
`X-Portal-Assertion`. `packages/extensionprotocol` verifies it. The token binds
issuer, audience, app ID, registration instance, key ID, boot ID, a random
nonce, a 30-second lifetime, the method, the exact path and query, the SHA-256
of the body, and the viewer: an opaque subject, role, session revision and
opaque OU identifiers. Rules that follow:

- Verify before reading anything else, pass the request URI exactly as received
  (`r.URL.RequestURI()`) and the exact body bytes (`nil` for a GET).
- A token verifies once. Replays and a full replay store fail closed.
- The assertion proves the viewer at the moment of the request. Authorize with
  it per request. Never cache it, store it, or log it.
- Portal sends no cookies or `Authorization`; `api.go` refuses them if they
  appear. The frontend cannot choose a URL, header or identity: `useAppBackend`
  sends only `{method, path, body}`.
- Responses are JSON up to 1 MiB (the relay's bound). Page larger data. The
  statuses 400, 403, 404, 409, 422 and 429 reach the frontend as ordinary
  responses ([backend-v2.md](backend-v2.md)); treat any other status as a failure.

**Task identity.** A task request carries `X-Portal-Service-Identity`, a JSON
grant whose MAC is keyed with a seed only Portal holds, so the backend cannot
verify the MAC. Portal verifies it before dispatch. The backend checks what it
can (app, installation, epoch, generation, policy revision, release, resource
list, a lifetime of at most five minutes) to catch drift and misrouting, and the
socket itself, reachable only by the runner, is the boundary. Never accept a
task request that also carries a viewer assertion.

## 3. The sandbox

The runner creates the container from the descriptor; the app chooses none of
it. The table is the policy in
`internal/apprunner/driver/container.go` (Portal), which
[`scripts/run-backend-local.py`](../scripts/run-backend-local.py) reproduces.

| Constraint | Value | What it means for your code |
| --- | --- | --- |
| User | `65532:65532` | The image's files must be readable and executable by this user. |
| Root filesystem | read-only | No writes outside the mounts below. Byte-compile or unpack at image build time. |
| `/data` | the installation's data, bind mount | The only persistent, writable place (read-only during a candidate start). A byte and inode quota applies (XFS project quota). |
| `/tmp` | tmpfs, 16 MiB, `noexec`, `nosuid`, `nodev` | Scratch only; no executables, small. |
| `/run/portal-app/http` | writable | The service socket. |
| `/run/portal-app/broker` | read-only | `registration.json`, `broker.sock`. |
| Network | none (`--network none`) | No DNS, no sockets to anywhere. Outbound HTTPS only through section 8. |
| Capabilities | all dropped, `no-new-privileges` | No `ping`, no binding below 1024, no `chown`. A seccomp profile narrows the syscalls further. |
| Memory / CPU / PIDs | from `backend.resources` (16-4096 MiB, 25-4000 millicores, 16-1024) | Swap equals memory (none). Exceeding memory is an OOM kill. Size `pids` for threads and child processes. |
| Open files | 1024 | |
| Shared memory, IPC, cgroup namespace | 16 MiB, private, private | |
| Environment | `PORTAL_APP_HTTP_SOCKET`, `PORTAL_APP_BROKER_SOCKET` (plus the proxy variables, section 8) | Nothing else: no secrets, no config. |
| Stop | `SIGTERM`, 10 s | Stop serving, flush, exit. Work in flight is retried. |
| Restart | none by the container | The runner owns the lifecycle. |
| Platforms | `linux/amd64`, `linux/arm64` | Declared in `backend.platforms`; one image per platform. |

Configuration that a person chooses (thresholds, recipients, destinations)
belongs in app-managed storage and UI, not environment variables or files in the
image. Secrets are never in the image: a backend never holds a credential value
(section 5, `secrets.use`).

## 4. Declaring the backend

`app.v2.json` gets a `backend` block and the capability lists. The template's:

```json
"backend": {
  "kind": "oci",
  "image": "ghcr.io/example/my-app@sha256:cccc...",
  "platforms": ["linux/amd64"],
  "protocol": "portal.backend/1",
  "resources": { "memory_mib": 128, "cpu_millis": 250, "pids": 64 }
},
"capabilities": { "required": [], "optional": ["background.run", "tasks.schedule"] }
```

`image` is a placeholder registry reference. A package carries its image
instead: `build-app-v2.py --images` replaces `image` with `images`
([section 11](#11-build-sign-install)). Declared capabilities are requests; the
administrator grants them, each capability is off until then, and an app must
work (or say clearly why it cannot) when an optional one is denied.

## 5. Capabilities

A capability is declared under `capabilities.required` (install is refused
without it) or `capabilities.optional`. The descriptor schema defines the
following 17. "Where" says which side uses it.

| Capability | Where | Declare | An administrator reviews |
| --- | --- | --- | --- |
| `background.run` | backend | list; needs a `backend` | That the app may run with nobody signed in. Needed by `tasks.schedule`, `events.subscribe` and `network.proxy`. |
| `tasks.schedule` | backend | list; needs `background.run` | That the app may queue background tasks (section 6). |
| `events.subscribe` | backend | list; needs `background.run` | Event delivery to the backend (Portal doc 159). The template has no handler. |
| `network.http` | frontend, backend | list only; destinations are **not** in the descriptor | The exact reviewed destinations (origin, path, method) and size/time limits; with `background.run`, also use while no one is signed in (docs 140, 174, 175). |
| `network.proxy` | backend | **optional only**; needs `background.run`; needs a `network_proxy` block of 1-64 `hosts` that pre-fills the review | The reviewed host list and daily byte budget (section 8, doc 184). |
| `network.stream` | frontend | list | Streaming reads from reviewed destinations (doc 158). |
| `network.postgres` | backend | **optional only**; needs a `backend` | Exact `host:port/database` targets for a fixed liveness check; the app never sees a stream or the password (doc 178). |
| `secrets.use` | frontend, backend | list; used with `network.http` | Which stored credential may be attached to which reviewed target, and for which principals (viewer, service). The app names a credential; Portal places the value, or signs the request (ACS3), and the app never reads it (docs 176, 177). |
| `secrets.read` | frontend | list | Exceptional raw credential access, reviewed per binding with a disclosure warning (doc 02). In the current code the raw-read operation is refused and no plaintext-read endpoint exists (docs 150, 176), so do not declare it. |
| `notifications.publish` | frontend, backend | list | That the app may raise notices into the administrator's existing notification rules. It chooses no recipient or channel (doc 152). |
| `reports.read` | frontend | list | Reading the current viewer's visible reports (doc 147). |
| `storage.files` | frontend | list | Private per-account objects with a quota; uninstall deletes them (doc 149). |
| `files.export` | frontend | list | A deliberate user download of an approved file kind and size (doc 02). The template has no example. |
| `principals.read` | frontend | **optional only** | Listing user and OU names for grant pickers; off after install and after every update until enabled (doc 181, [principals-v2.md](principals-v2.md)). |
| `public.projection` | backend | **optional only**; plus a `public` block (routes, optional document) | Anonymous read-only JSON routes and an optional public page, with cache and size limits (doc 179). |
| `ingress.webhook` | backend | **optional only**; plus an `ingress` block (1-4 routes) | Each route and its inbound address pattern; each sender endpoint is a separate credential binding (doc 180). |
| `machine.read` | backend | **optional only**; plus a `machine` block (1-32 routes) | The routes a machine client may read, and the tokens an administrator issues for them (doc 183). |

Dependency rules from the descriptor parsers (the SDK's and Portal's):

- **Optional only** (a descriptor listing one under `required` is refused):
  `principals.read`, `public.projection`, `network.postgres`, `ingress.webhook`,
  `machine.read` and `network.proxy`. Each is an administrator's decision, never a
  condition of install.
- **Need a backend**: `background.run`, `tasks.schedule`, `events.subscribe`,
  `public.projection`, `network.postgres`, `ingress.webhook`, `machine.read` and
  `network.proxy`.
- `tasks.schedule` and `events.subscribe` need `background.run`, and if one is
  required, `background.run` must be required too. `network.proxy` needs
  `background.run` (in either list).
- `network.proxy` and the `network_proxy` block stand or fall together: the block
  without the capability, or the capability without at least one host, is refused.
  The same pairing holds for the `public`, `ingress` and `machine` blocks and their
  capabilities.
- A capability is in at most one list.

How the capabilities reach your code:

- **Frontend capabilities** (`reports.read`, `storage.files`,
  `notifications.publish`, `network.http`, `principals.read`...) are hooks in
  `@portal-app/sdk/root-v2`. They do not touch your backend. `useAppBackend` is
  independent of any capability: every installed backend is reachable by its own
  frontend.
- **Backend capabilities that give your service a call out** use the broker
  socket, `portal.broker/1`, HTTP/1.1 and JSON over
  `PORTAL_APP_BROKER_SOCKET`. The socket is the identity; send none.
  `POST /v1/network/http` (a reviewed `network.http` call, optionally with a
  `credential` name or an ACS3 `signing` object), `POST /v1/notifications`,
  `POST /v1/postgres/liveness` and `GET /v1/status` (egress state and the
  resources granted). Errors are `{"error":"invalid|denied|unavailable|busy|uncertain|conflict|capacity"}`.
  `uncertain` means the request may have reached its destination, so the app
  owns the retry decision. The socket exists only while Portal holds the
  installation's egress session, so a call before the first session fails to
  connect, and between sessions answers `unavailable`: treat both as "try
  later". There is no broker client library in this repository yet; see "Not yet
  available".
- **Capabilities that bring traffic in** (`public.projection`,
  `ingress.webhook`, `machine.read`) arrive on the reserved route spaces
  (section 9). Declaring one without implementing its routes is a mistake, and
  implementing routes without declaring it is dead code.

**Review is the product.** Everything an administrator reads comes from your
descriptor and the review pages, so keep it small and truthful: declare only
what the code uses, as optional unless the app is useless without it, prefer a
brokered credential over holding one, and put `network_proxy.hosts` only for
hosts the code reaches. The template's `descriptor_test.go` keeps the
descriptor and the code consistent; extend it when you add a capability.

## 6. Background tasks

`background.run` plus `tasks.schedule` let Portal call `POST /v1/tasks/run` with
no user present. The request is the closed object `{format, task_id,
occurrence_id, payload}` with `format` `portal.app-task.request/1-dev.1`; the
answer is `portal.app-task.response/1-dev.1`, canonical JSON, with an `outcome`
and an optional `error_code`, `result` and `evidence_sha256`. The outcomes:
`succeeded`; `failed` (final); `retry` (Portal delivers the same occurrence again
after its own backoff, up to five attempts, then marks it failed; the backend
cannot choose the delay); and `uncertain` (never retried automatically). Use
`retry` for a refusal that may pass, such as a full queue, and `failed` for one that
will not.

**A task execution has 45 seconds** (the task worker's deadline). Anything
longer is abandoned and classified uncertain, which Portal never retries
automatically. So the handler **enqueues and returns at once**: validate the
request and identity, record the work durably, answer. The template does
exactly that:

1. `api.go` checks the request shape, refuses a viewer assertion, validates the
   service identity for the `tasks.schedule` resource, and parses the payload
   strictly.
2. `Queue.Submit` (`tasks.go`) writes one file per `occurrence_id` under
   `/data/queue` (created by the first task, not at startup, because the
   descriptor promises `writes_on_startup: false`) and returns `duplicate: true`
   for a repeat. The same occurrence arrives again after a `retry` answer, a
   restore or an operator action, so it must not run twice.
3. A worker goroutine runs the job later. A job still pending at a restart is
   queued again, and so is one whose handler failed when its occurrence is
   submitted again. So a job runs **at least once**: make it idempotent.

Replace `jobs["example"]` with your work. Keep the queue bounded (it answers
`retry` with `run_queue_full`), keep results small, never put a secret, URL, path or
destination in a payload (the platform refuses them), and let the app, not the
payload, decide what a job may reach. If work is long, report progress through
your own viewer routes. Examples of heavier designs are in
`apps/kazuha-hub-market-monitor/service` (`jobs.go`, `scheduler.go`: a process group per
job, a persisted run history, an internal schedule).

## 7. Outbound traffic at a glance

| Need | Use |
| --- | --- |
| A few reviewed JSON calls, possibly with a credential or a signature, with per-call limits | `network.http` (frontend `useAppNetwork`, or the broker's `POST /v1/network/http` from the backend) |
| Third-party code or bulk reads of many reviewed hosts over TLS | `network.proxy` |
| A credential that must stay out of the app | `network.http` with `secrets.use`. `network.proxy` cannot carry one. |
| A check that a PostgreSQL server answers | `network.postgres` |
| A private-network or plain-HTTP target | `network.http` with an operator-allowlisted target (doc 175). `network.proxy` refuses IP literals and private addresses. |

## 8. Outbound HTTP: `network.http` or `network.proxy`

Both reach only what an administrator reviewed, and a container never gains a
network interface.

**`network.http`** is one signed, reviewed request per call. Portal checks the
request against the reviewed policy (origin, paths, methods); the runner
executes it. Limits: request at most 64 KiB, response at most 1 MiB, 15 seconds,
at most 4 concurrent calls, and for the background path 120 calls per minute with
a burst of 20. A call is audited. Because Portal sees each request it can attach
a credential (`secrets.use`) or sign it (ACS3), and plain HTTP and private
targets are possible when an operator allowlists them. Use it for:
authenticated APIs, small JSON, anything where per-call review matters. From the
backend, send `POST /v1/network/http` to the broker socket. The destinations
are reviewed targets, not descriptor fields; an app can request them in-app (the
SDK's `useAppNetworkTargets`), and the administrator decides.

**`network.proxy`** reviews hosts, not requests. A forwarder inside the
container (`packages/proxy`) listens on `127.0.0.1:3128` and relays each
`CONNECT host:443` over the broker socket. The broker checks the host against the
reviewed list, resolves it, refuses private and reserved addresses, dials one
pinned address, requires the TLS ClientHello's SNI to equal the CONNECT host,
then splices bytes. TLS stays end to end, so libraries that impersonate a
browser handshake keep working, but the platform cannot see paths or bodies and
cannot attach a credential. Limits: 16 open tunnels, 300 new tunnels per minute
(burst 50), 60 s idle, 10 minutes lifetime, a daily byte budget of 2 GiB that an
administrator can only lower, 64 tunnels per runner. Use it for: scraping and
third-party libraries that speak to many hosts, large responses, anonymous reads.

Declare it:

```json
"capabilities": { "required": [], "optional": ["background.run", "tasks.schedule", "network.proxy"] },
"network_proxy": { "hosts": ["*.example.com", "api.example.org"] }
```

`hosts` is sorted, unique, at most 64: an exact lowercase host, or `*.` plus a
registrable domain or deeper. A wildcard matches exactly one label in front.
Port 443 only. The list is a suggestion; nothing is allowed until an
administrator reviews it, and until then every CONNECT is refused.

For an app that declares `network.proxy` the runner sets, whether or not it is
granted, `HTTPS_PROXY` and `https_proxy` to `http://127.0.0.1:3128`, `NO_PROXY`
and `no_proxy` to `127.0.0.1,localhost`, and `PORTAL_APP_PROXY_LISTEN`.
**`HTTP_PROXY` and `ALL_PROXY` are never set**: use `https://` URLs. The
template starts the forwarder only when `PORTAL_APP_PROXY_LISTEN` is present
(`egress.go`), so an app that does not declare the capability runs nothing extra;
the broker socket alone cannot start it, because Portal always sets that one.
`newEgressClient(http.ProxyFromEnvironment)` returns an HTTPS-only client that
does not follow redirects (a redirect could name an unreviewed host) and reports
the broker's refusal as `*RefusalError`: `not_granted`, `host_not_reviewed`,
`port_not_permitted`, `address_denied`, `resolve_failed`, `connect_failed`,
`busy`, `budget_spent`, `unavailable`. Handle it like any failing upstream.
Bring CA certificates (the template image copies them) because the service
terminates TLS itself.

For a Python or other non-Go worker, run the same forwarder as a static binary:
`CGO_ENABLED=0 go build ./cmd/portal-egress-proxy` in `packages/proxy`, and
start it before the code that needs the network. An app may hold both
capabilities: `network.http` for credentialed calls, `network.proxy` for bulk
anonymous reads. See [backend-v2.md](backend-v2.md#outbound-https-from-a-backend)
and Portal doc 184.

## 9. Reserved route spaces

Three path spaces under `/v1/` belong to capabilities, not to viewer routes. The
runner picks the assertion header from the token's prefix and refuses any
cross-combination (a viewer token on a reserved path, a reserved token on a
viewer path, the wrong method). Your backend must still verify what it receives.

| Space | Capability | Method | Header | Token | Carries |
| --- | --- | --- | --- | --- | --- |
| `/v1/...` (everything else) | none | GET/POST/PUT/DELETE | `X-Portal-Assertion` | (none) | the current viewer |
| `/v1/public/` | `public.projection` | GET | `X-Portal-Public-Assertion` | `pub.` | route ID, path, query digest; **no viewer** |
| `/v1/ingress/` | `ingress.webhook` | POST | `X-Portal-Ingress-Assertion` | `ing.` | route, endpoint, receive time, nonce digest, body digest; no secret, no address |
| `/v1/machine/` | `machine.read` | GET | `X-Portal-Machine-Assertion` | `mch.` | route, client ID and label; no viewer, no secret |
| `/v1/tasks/run` | `tasks.schedule` | POST | `X-Portal-Service-Identity` | (JSON) | the background service grant |

Each token has its own MAC domain, so one kind never verifies as another.
Consequences for your code:

- Public routes serve anyone on the internet, so return only what you would
  publish, bounded by `response_bytes`, and deterministic enough to cache for
  `cache_seconds`.
- An ingress route answers for an external sender Portal already authenticated
  (HMAC over route, endpoint, time, nonce and body). The backend receives the
  verified fact and a nonce digest; deduplicate durably on the digest.
- A machine route is read-only by contract and, in the answer, may pass 400, 404
  and 422 JSON through to the caller. The caller never sees your viewer rules.
- `packages/extensionprotocol` verifies the viewer assertion
  (`Verifier.Verify`) and the machine assertion
  (`Verifier.VerifyMachineAssertion`, which expects the full request target
  including its query). It does **not** yet verify `pub.` or `ing.`
  tokens (see "Not yet available").
- The template answers 404 on all three spaces, since it declares none of the
  capabilities.

## 10. Run it locally

```sh
python3 scripts/run-backend-local.py my-app --build        # docker build, then start
python3 scripts/run-backend-local.py my-app --call GET /v1/hello --role admin --ou ou-a
python3 scripts/run-backend-local.py my-app --task '{"job":"example"}' --occurrence run-1
python3 scripts/run-backend-local.py my-app --logs
python3 scripts/run-backend-local.py my-app --stop         # or --clean to delete the local data
```

What it does:

1. Reads `app.v2.json` for the resource limits and whether `network.proxy` is
   declared (so the proxy variables match what Portal would set).
2. Builds the image if asked (`docker build -f apps/ID/service/Dockerfile .`).
3. Starts it as `portal-local-ID-<hash of the checkout>` (so two checkouts or users on one Docker daemon do not collide) with the constraints of section 3: user
   65532, read-only root, `--network none`, capabilities dropped, a 16 MiB
   `noexec` `/tmp`, the descriptor's memory, CPU and PIDs, and exactly three bind
   mounts: `apps/ID/.development/local/data` at `/data` (writable;
   `--data-readonly` for a candidate start), `http/` at the socket directory,
   and `broker/` (read-only) holding `registration.json`. Nothing is
   published to a host port. The two writable directories are mode 1777 (the
   container user is not you), and the dev registration is mode 0644 because that
   user must read it: it is a throwaway key for this backend only.
4. Calls it. The socket belongs to uid 65532 with mode 0600, so a call runs a
   throwaway container from the same image, with the same sandbox, and the
   **dev client** mounted as its entrypoint.

**The dev signer.** `packages/extensionprotocol/cmd/portal-dev-client` stands in
for Portal. `register` writes a registration with a freshly generated key and
deployment ID `portal-dev-local`; `call` does the boot handshake, signs a viewer
assertion for the role, subject and OUs you give, and sends one request; `task`
sends a task with a fabricated service identity that passes the fields the
backend can check. It is **development only** and cannot act on a real
installation: the key is its own, the backend started by the script trusts only
that key, and the client refuses any registration it did not write. The viewer
facts are whatever you type, so authorization you test here is as real as your
own inputs; it exercises your code's use of the assertion, not Portal's issuing
of it.

`--broker-socket PATH` mounts a Unix socket of your own as `broker.sock`. The
script does not provide a broker. Without one, calls to the broker socket fail to
connect, as they do in Portal before the first egress session, and a declared
forwarder answers CONNECT with `403 X-Portal-Proxy-Refusal: unavailable`.

What a local run does **not** reproduce: the runner's seccomp profile (Docker's
default applies), XFS quota on `/data`, CPU pinning, the egress session and the
broker itself, Portal's task scheduling and retries, the relay's response bound
and timeouts, and identity facts from a real session. Run it on Linux Docker
(rootless Docker is unsupported by the runner and untested here). The script
needs Go on the host to build the client.

## 11. Build, sign, install

The pipeline, and where each step stops being scripted:

```text
docker build          apps/my-app/service/Dockerfile        (this repo, local)
docker save           image.tar                              (local)
export-image-oci.py   images.json + blobs/                   (this repo, local)
build-app-v2.py       descriptor.json + frontend.zip         (this repo, local, unsigned)
sign descriptor.json  descriptor.sig                         (NOT in this repo)
pack-offline-envelope my-app.portalapp                       (this repo, local)
register the key      Portal admin                           (Portal)
stage + install       Portal admin                           (Portal)
```

**1. Build and export the image.**

```sh
docker build --platform linux/amd64 --tag my-app:build -f apps/my-app/service/Dockerfile .
docker save "$(docker image inspect my-app:build --format '{{.Id}}')" --output image.tar
python3 scripts/export-image-oci.py image.tar --platform linux/amd64 --output apps/my-app/.development/image
```

`backend.platforms` must equal the exported platforms. Zstd, foreign layers and
layers with URLs are refused. The runner loads this image by content ID; it
never pulls.

**2. Build the unsigned candidate.**

```sh
python3 scripts/build-app-v2.py my-app \
  --images apps/my-app/.development/image/images.json \
  --output apps/my-app/.development/candidate
```

This builds the frontend and writes `frontend.zip` and `descriptor.json` (strict
parse and the real ZIP digest; `backend.image` becomes `backend.images`). The
descriptor's `publisher` and the app ID must match a publisher enrolled in the
Portal you install into (prefix grants such as `notes-` are common). Without
`--images` the descriptor keeps its registry reference; a runner accepts that only
in its development profile, `allow_local_reference_images`, for an image already
present on its Docker daemon. A production profile refuses it with
`reference_image_refused`.

**3. Sign.** Sign the exact bytes of `descriptor.json` with an Ed25519 key whose
public half an administrator enrolls. The signature covers
`"portal.app/descriptor/v2" || 0x00 || uint64_be(len(descriptor)) || descriptor`.
The detached `descriptor.sig` is JSON of at most 4096 bytes with exactly six
fields: `format` (`portal.app.signature/1-dev.1`), `algorithm` (`Ed25519`),
`publisher`, `key_id`, `descriptor_sha256`, and `signature` (86 characters of
unpadded base64url). No tool in this repository or in Portal's tree does this
(see "Not yet available"). The format is Portal doc 24.
[publisher-v2.md](publisher-v2.md) has the verifier and its public test corpus; the
corpus key is public test material, never enroll it.

**4. Pack.**

```sh
python3 scripts/pack-offline-envelope.py \
  --descriptor apps/my-app/.development/candidate/descriptor.json --signature descriptor.sig \
  --frontend apps/my-app/.development/candidate/frontend.zip \
  --image-blobs apps/my-app/.development/image/blobs --output my-app.portalapp
```

The packer verifies the descriptor, the frontend digest and every image blob
against the signed descriptor, and refuses over 160 entries or 384 MiB. A
Portal checkout can inspect the result without running anything:
`GOWORK=off go run ./cmd/app-inspect -envelope my-app.portalapp`.

**5. Trust the publisher in a Portal.** An administrator opens application
management, then Publishers (Portal docs 63, 64).

- A brand-new deployment first runs "Initialize application platform" once.
- Register the publisher: ID, namespaces (the exact app ID or a hyphen-terminated
  prefix), and your Ed25519 public key (a key ID and 43 characters of unpadded
  base64url). A registration starts **disabled**; review it, compare the key's
  SHA-256 fingerprint through a channel you trust, then enable it.
- The Portal origin you passed as `--parent-origin` is the **trusted development
  parent origin**: it is compiled into `frontend/src/bootstrap.json`, accepted as
  canonical HTTPS or exact loopback HTTP with an explicit port, and never taken
  from a URL, referrer or message. For a development Portal at
  `http://127.0.0.1:31935` it is that string. A frontend built for one origin
  does not work in another: regenerate or edit `bootstrap.json` and rebuild.

**6. Stage and install.** Staging puts verified bytes in the release store; it
does not install.

- Offline: an administrator posts the `.portalapp` to
  `POST /api/admin/app-platform/market/offline` (`Content-Type:
  application/zip`). Version 2 envelopes carry managed images.
- Online: a catalogue (`portal.catalogue/2-dev.1`; Portal doc 170 plans
  `2-dev.2` with a `package_url` for managed packages, not checked
  against the code here) at a public HTTPS URL on port 443, with canonical paths. Portal
  refuses private and loopback hosts for it.

Then, in application management, choose the audience (users or OUs), read the
review (capabilities, resources, data policy) and confirm. For a managed app the
Portal needs a runner: Linux, rootful Docker, and XFS volumes with project quota
(Portal handbook sections 4 to 4.4). A host without one installs static apps
only.

## 12. Not yet available

Plainly, so nobody discovers it at the last step:

- **A signing tool.** Neither this repository nor Portal ships a command that
  signs a descriptor or writes `descriptor.sig`. The framing is specified
  (section 11, step 3) and the verifier is tested, so a short script with a
  standard Ed25519 library can do it, but it is not provided or tested here, and
  there is no development publisher key to borrow: you generate your own and
  enroll its public half.
- **An upload control for `.portalapp` files.** The offline route is an
  administrator API; Portal doc 157 lists a browser upload control as remaining
  work. The route needs an authenticated administrator session. A loopback or
  private development Portal cannot use the online catalogue (public HTTPS only).
- **Verified end-to-end installation of this template.** The template is checked
  to build, vet, test and produce a candidate, and the local run is exercised
  against a real container. Nobody has yet signed, packed and installed one into a
  running Portal from this repository; the steps in section 11 come from Portal's documents and code,
  so confirm them against your Portal build.
- **`pub.` and `ing.` assertion verifiers.** `packages/extensionprotocol` verifies
  viewer and `mch.` tokens. Public-projection and ingress backends need the
  `pub.` (MAC domain `rp-extension-public-v1`) and `ing.` (`rp-extension-ingress-v1`)
  formats of Portal docs 179 and 180 and would have to implement them; the
  package only has negative test vectors for them.
- **A broker client.** No Go package wraps `portal.broker/1`
  (`POST /v1/network/http`, `/v1/notifications`, `/v1/postgres/liveness`,
  `GET /v1/status`). Write against the documented JSON, and test with
  `--broker-socket` and a listener of your own.
- **Local run fidelity.** Section 10 lists what is not reproduced. There is no
  local Portal and no fake host with sessions, so frontend and backend are
  exercised separately: the frontend with the SDK's bridge host in tests (as the
  template does), the backend with the dev client.
- **A stable contract.** Formats carry `-dev` versions, the template is a
  provisional development starter, and a local candidate is not a release.
  Publication to the catalogue is a separate, gated process
  ([root-v2.md](root-v2.md), [plugin-development-standard.md](plugin-development-standard.md)).

## 13. Sources

Portal repository, `docs/app-platform/`: `07-handbook.md` (developer and
operator workflows, runner setup), `24` (signatures), `63`/`64` (publishers),
`157`/`170` (envelope and images), `174` (background broker), `175` (network
targets), `176` (credentials), `177` (ACS3), `178` (PostgreSQL), `179` (public),
`180` (ingress), `181` (principals), `182` (runtime and XFS), `183` (machine
read), `184` (forward proxy). In this repository: [descriptor-v2.md](descriptor-v2.md),
[network-v2.md](network-v2.md), [principals-v2.md](principals-v2.md),
[publisher-v2.md](publisher-v2.md), [platform-contract.md](platform-contract.md).
