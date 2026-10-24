# PostgreSQL monitoring without a gateway container

The explicit local Unix socket transport replaces the need for a TLS gateway on
a host where Status and PostgreSQL share a kernel. It does not change PostgreSQL's
native TLS setting or add a service. Remote/network monitors continue to require
verified TLS with no plaintext fallback.

## Trust and storage boundaries

The administrator mounts one trusted PostgreSQL socket file read-only at
`/run/status-postgres/.s.PGSQL.5432`. A monitor selects `postgres_transport: unix`,
the socket's port number, a database and a separately sealed PostgreSQL credential.
There is no configurable arbitrary socket path. The example below uses port 5432;
another port requires both the corresponding mount target filename and monitor
port. A missing source must fail deployment rather than create a directory.

The adapter verifies that the fixed directory is a real directory and its selected
file is a socket, rejecting symlinks and regular files. Every dial is checked
again against the exact Unix network and socket filename. Driver DNS lookups,
alternate paths, TCP endpoints and fallback connections are refused. Authentication,
query and cleanup retain the existing context bounds; the only query is `SELECT 1`.
Startup requests read-only transactions in addition to the dedicated role policy.

Filesystem isolation replaces network encryption for this explicit local route.
The deployment administrator must trust the host PostgreSQL socket and its owner.
Do not mount the Docker socket, the whole host `/tmp` directory or a broad host
filesystem. A privileged host administrator remains inside this trust boundary.
This transport is not an encrypted network tunnel and cannot reach a database on
another machine.

No table, column or migration changes. The transport is an optional field in the
existing version-1 monitor configuration. Existing configurations still select
verified network TLS. The frontend requires backend capability
`status.postgres-unix.v1`, so an older service is refused before app data loads.

## Deployment and configuration

Use a matching verified Status frontend/service build containing this capability.
The older prepared service and ZIP cannot enable it merely by mounting a socket.
Status remains subject to its release, market installation and pairing gates.

1. Have the database administrator verify the actual socket file, its owner and
   its containing directory permissions. Retain the dedicated probe login; do not
   substitute Portal/Dify application credentials or a superuser.
2. If the dedicated login is currently denied local access, review a narrowly
   scoped `local` authentication rule for that exact database and role using
   SCRAM. Preserve unrelated rules, validate the authentication file, then reload
   it. Do not grant access to application tables or change native database SSL.
3. Add the optional mount override to the Status deployment:

   ```sh
   export STATUS_POSTGRES_SOCKET=/absolute/trusted/path/.s.PGSQL.5432
   docker compose -f compose.yaml -f compose.postgres-unix.yaml config
   ```

   Resolve and inspect the configuration on the deployment host. Resolved Compose
   output can contain secrets; keep it private. The override creates no service
   and changes no network exposure. Start only after matching artifacts, pairing
   and initial pause settings have been verified.
4. In the private Status management UI choose **PostgreSQL**, **Local Unix socket**,
   port **5432**, the database and the dedicated saved credential. Hostname and
   private CIDRs are not part of this mode. Switching from TLS does not retain
   those destinations in the saved local configuration.
5. Keep the component administrator-only, publication disabled and normal
   scheduling paused during the initial bounded check. Require actual
   `read_query_only` evidence and negative credential/database controls before
   enabling its schedule. A saved form or container mount is not query evidence.

For network mode, choose **Network with verified TLS** and configure its verified
hostname and explicit private network allowance as before. Socket failure never
changes that mode, downgrades TLS or restarts PostgreSQL.

## PostgreSQL restart and rollback

A socket file bind mount pins its inode. PostgreSQL may replace its socket after
a restart. The old mount then fails; recreate the Status container so Docker binds
the current verified source file, and require a fresh successful observation.
Do not rely on a simple Status process restart inside the existing container.
Native database replacement and socket ownership changes need the same review.

To withdraw local monitoring, pause or disable its monitor, stop Status when
changing its mounts and remove this optional override. Revoke only the dedicated
local role rule if it is no longer needed, preserving other database users.
Restoring an older app or database backup does not authorize reactivating the
removed gateway. Future network mode requires a separately verified native TLS
endpoint, not an automatic helper container.

## Verification scope

Unit fixtures exercise real Unix sockets and the PostgreSQL wire protocol for
`SELECT 1`, stalled authentication/query deadlines, exact destination checks,
missing sockets, replacement files, symlinks and cancelled dials. Existing TLS
fixtures continue to require trusted certificates and reject plaintext fallback.
The browser fixture saves and reopens a local monitor, switches transport modes
and verifies network destinations are omitted after returning to local mode.

## Authorized target acceptance

On 2026-10-24 the actual adapter from source
`bef2b1f6f0b68b64756ea7525d2424807675e197` passed a one-shot target check.
Both exact-source CI runs (`40069194726`, `40069216454`) passed before the target
authentication adjustment. The Linux harness SHA-256 is
`4ef8f50d5ae435a347edf1158061c600a8cc4d1a3dd02837d690a3149ac42990`;
its source SHA-256 is
`296168c22baf224562e0933ade3fda4d4057b50a783ef6eac81449376ceb1bc5`.

The initial check was refused by the previous local authentication rule. Only the
dedicated `portal_status_probe` block was adjusted: allow SCRAM for that role and
`report-portal` over local sockets, then reject its other local database and all
network access. Other authentication rules were byte-preserved, parsing returned
zero errors, and native SSL stayed off. The existing role was verified without
elevated privileges, memberships, business-table privileges or schema creation.
No database schema, application account or password was changed.

At `2026-10-24T06:17:21Z`, the one-shot container ran as UID/GID 1001, with a
read-only root and socket mount, dropped capabilities and `--network none`.
It mounted only the PostgreSQL socket and the harness executable. Credentials
were provided through stdin in memory and excluded from receipts. Results:

| Case | Result |
| --- | --- |
| Dedicated role, target database | `success`, `read_query_only`, 2 ms |
| Wrong password | `failure`, `database_unavailable` |
| Different database | `failure`, `database_unavailable` |
| Unmounted port | `unknown`, `local_socket_unavailable` |

Portal database health and Dify health remained healthy. No gateway container,
production Status process, component, schedule or notification was enabled.
Protected evidence is under
`/data/report-portal/status-postgres/local-socket-acceptance-bef2b1f`:
`before-local-authorization.json`, `local-authentication-verification.json` and
`local-query-verification.json`. The previous/current authentication hashes are
recorded there, including protected recovery bytes. This is actual target query
acceptance, not an installed/paired production monitor or a database-restart drill.
