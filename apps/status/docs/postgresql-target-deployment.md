# Target PostgreSQL connection deployment

## Current state: gateway removed

On 2026-10-24 UTC the owner requested removal of the extra Status PostgreSQL
container. The unused `report-portal-status-postgres-status-postgres-tls-1`
container was stopped and removed. Portal and Dify remained healthy; the native
PostgreSQL service and its configuration were not changed. Protected deployment
files were retained for recovery, with `gateway-removal-verification.json` under
the directory below. Status remains stopped and unpaired.

The gateway path documented below is historical verification evidence, not a
currently available monitor destination. The local socket replacement now has
one-shot target query acceptance; production activation still needs matching
artifacts, pairing and configuration. Do not weaken verified network TLS or
automatically recreate this gateway as a normal Status rollout step. Retained
start commands are recovery reference only.

The [explicit local socket alternative](postgresql-local-socket.md) adds no helper
container and leaves native database SSL unchanged. Its runbook records actual
target authorization/query evidence as well as the remaining activation steps.

This records the authorized target deployment on 2026-10-23 Pacific. It is an
infrastructure runbook, not a new Portal migration or a completed Status rollout.
The server directory is `/data/report-portal/status-postgres`. It is owner-only;
credentials, private keys and the original authentication file must stay there or
in the approved secret manager, never in this repository or a release archive.

## Connection and privileges

```text
Status -> verified TLS -> status-postgres-tls:5433
                         -> private host TCP -> PostgreSQL:5432 / report-portal
```

TLS terminates at the dedicated PostgreSQL-aware gateway. The final hop is
explicitly plaintext on the same host's private bridge. Native PostgreSQL SSL
remains off; existing applications and their SSL settings were not changed. This
is not an assertion that the final database socket uses TLS. If that trust boundary
is unsuitable for another deployment, use native verified PostgreSQL TLS instead.
Never change the Status adapter to skip verification or fall back to plaintext.

The gateway uses stunnel's documented
[`protocol = pgsql`](https://www.stunnel.org/manual.html) negotiation, not a generic
HTTPS/TCP TLS listener. It accepts the PostgreSQL SSLRequest and rejects a
plaintext StartupMessage. Its certificate has DNS SAN `status-postgres-tls`.
The container has fixed address `172.22.0.10` on `report-portal_default`, no
published host port, UID/GID 1001, a read-only filesystem, dropped capabilities,
no-new-privileges, 32 PIDs, 64 MiB and 0.25 CPU.

The new `portal_status_probe` login has no role memberships, superuser, database
creation, role creation, replication or RLS-bypass privileges. Its connection limit
is two; default transactions are read-only with bounded statement, lock and idle
transaction timeouts. Only CONNECT was granted. The transactional privilege audit
refuses existing application table access, schema creation, application sequence
access and executable custom security-definer functions. No Portal business table
grant or schema change was made.

The authentication file has one marked block before its original, byte-preserved
rules. It applies only to this new login:

```text
# Status PostgreSQL probe access begin
local all portal_status_probe reject
host "report-portal" portal_status_probe 172.22.0.10/32 scram-sha-256
host all portal_status_probe 0.0.0.0/0 reject
host all portal_status_probe ::/0 reject
# Status PostgreSQL probe access end
```

The original file is protected as `pg_hba.before.conf`; hashes and the actual
configuration path are in `authentication-verification.json`. Parsing returned
zero errors before reload. Existing role rules were retained, and Portal health
remained `{"db":"ok","ok":true}` after gateway restart.

## Start, inspect and stop

Run on the target as the deployment account:

```sh
cd /data/report-portal/status-postgres
docker compose -p report-portal-status-postgres -f compose.json --profile tls up -d --no-build
docker compose -p report-portal-status-postgres -f compose.json --profile tls ps
```

`compose.json` pins local image ID
`sha256:a6668bdccd5d6bf08aadf6cd27d7cc9f88dd1f53fda746094f48b279a699678d`.
Its narrow `image/` build context contains no secrets. The Dockerfile pins Alpine
digest `sha256:28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b`
and installs `stunnel=5.82-r0`. A rebuild is a separate reviewed deployment:
record the resulting ID and change the pinned compose image deliberately.

Container running state alone does not prove query health. Require the actual
Status PostgreSQL monitor to report `read_query_only` after its guarded SELECT 1.
The target's one-shot adapter receipt is `query-verification.json`; restart and
negative controls are in `restart-and-boundary-verification.json`.

To stop only this gateway:

```sh
docker compose -p report-portal-status-postgres -f compose.json --profile tls stop
```

No other Portal, Dify or PostgreSQL service is stopped by that command.

## Finish Status configuration after marketplace installation

The candidate is still stopped, paused and unpaired. Its
`postgres-trust.override.json` only sets the infrastructure trust source
`SSL_CERT_FILE=/run/secrets/postgres-client-ca-bundle.crt`; the file under its
owner-only secrets directory contains public system roots plus the private CA.
Public roots remain available to DeepSeek and other HTTPS probes. The CA private
key is not mounted into either Status or the gateway; the gateway gets only its
leaf certificate and key.

When preparing the final release directory, preserve this combined trust bundle
and apply the equivalent environment override to the paired service. Validate the
resolved compose configuration before starting. Do not start the unpaired profile
as a workaround for installation or permission confirmation.

After market installation and private pairing, use the Status management UI to
save the dedicated credential from the protected
`secrets/database-credential.json`. Never print that file or put its password in
shell arguments, logs or chat. Password provisioning used psql's
[`\password`](https://www.postgresql.org/docs/16/app-psql.html) command with stdin
and SCRAM encryption, not a cleartext SQL PASSWORD literal.

Create the PostgreSQL monitor with host `status-postgres-tls`, port 5433, database
`report-portal`, and approved network `172.22.0.0/16`. Keep its component
administrator-only and public access/outbox paused until policy review. Prove a
manual read-only check before enabling its schedule. Do not substitute an existing
Portal/Dify database login or grant SELECT on business tables.

Once the credential is sealed in Status and its protected recovery copy is
confirmed, retire the plaintext bootstrap handoff according to the secret policy.
The SQLite backup does not include this external database role, CA or gateway.

## Rotation, recovery and removal

The current leaf certificate expires at `2027-04-22T03:41:54Z`; renew before that
date, preferably at least 30 days earlier. Keep the hostname SAN, serverAuth usage
and trusted issuer. Verify a new leaf against the CA before activation. Stage new
files, retain protected previous copies and recreate the gateway after replacement:

```sh
docker compose -p report-portal-status-postgres -f compose.json --profile tls up -d --force-recreate --no-build
```

File bind mounts can retain old inodes after atomic file replacement; a process
restart alone is not the certificate replacement procedure. Verify the presented
leaf and actual SELECT 1 after recreation. The fixed private address must remain
172.22.0.10 or the scoped authentication rule will correctly refuse it.

CA rotation requires staging a combined old/new trust bundle in Status first,
recreating Status so its running trust state refreshes, switching the gateway leaf,
testing, and only then removing obsolete trust. Pause affected probes during the
operation and review abandoned evidence; never disable verification to recover.

For password rotation, pause the affected monitor, change only the dedicated role
through the protected administrative channel and update its Status credential.
Require a fresh successful probe before scheduling again. Do not change the
business application's database password.

For removal, pause the monitor, disable this login, stop the gateway and remove
only the marked authentication block from the current file. Back up first, check
`pg_hba_file_rules` for errors and reload. Restore the entire old file only when
its current hash matches the recorded deployed hash; otherwise preserve unrelated
subsequent edits. An optional role deletion must first revoke its CONNECT grant
and verify it owns no objects. No Portal migration marker is deleted or rewritten.

Keep private CA/key material and credential recovery copies in protected storage.
The prepared infrastructure archive is
`/data/report-portal/backups/status-postgres-20261024T040425Z/infrastructure.tgz`.
Its owner-only verification receipt records sixteen file hashes checked after
isolated extraction and a valid restored certificate chain. Scratch copies were
removed. This tests file recovery, not a restore into the live database or an
automatic role/pairing reactivation. Keep an approved protected off-host copy;
another file on the same host alone does not survive loss of the host.
Restoring Status still follows the normal paused-probe/outbox/public-off review;
an infrastructure restore does not authorize resuming an old backend pairing.
