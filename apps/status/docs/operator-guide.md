# Status operator guide

## Scope and prerequisites

This runbook applies to the unreleased `0.1.0-dev` development build. Do not change
the Portal default marketplace or install it into production until the acceptance
checklist and both dependency PRs are approved. The application sources remain in
the shared Apps monorepo; no separate Status repository is needed.

Use a Portal build containing notification PR #141 and platform PR #142. The
Portal connection uses migration 0008; its frozen baseline is unchanged. Back up
Portal before upgrading, following its existing backup runbook. Status has its own
SQLite database and its own backup procedure below. They are separate backups.

Provide a private service network or verified HTTPS endpoint for Status. Do not
publish its private `/v1/*` API, heartbeat ingress or health endpoints through a
broad public reverse-proxy rule. Restrict heartbeat ingress to the job networks
that need it. The public gateway template only exposes an exact allowlist.

## Build the executable and ZIP

From the Apps repository root:

```sh
python3 scripts/build-status-frontend.py
python3 scripts/catalogue.py package status
cd apps/status/service
GOWORK=off GOTOOLCHAIN=go1.26.10 go build -trimpath -o ./status ./cmd/status
```

Move the executable to your service directory. Prepare a writable data directory
and a separate secrets directory owned by the service account. Do not put them in
the repository, web root, application ZIP or a shared writable directory.

Generate the storage encryption key once:

```sh
./status keygen -file /srv/status/secrets/status-storage.key
```

The command refuses to overwrite an existing file. Keep the key in your secret
manager with a protected recovery copy. Losing it makes saved credentials
unrecoverable. Files containing storage keys or pairing data must have owner-only
permissions, normally `0600`; the service refuses wider permissions.

## Install and pair the private application

1. Sign in to Portal as an administrator. Open application management and upload
   `dist/status/0.1.0-dev/status.zip`. Review `extension.read` and
   `extension.manage`. These scopes grant neither report ingestion nor unrestricted
   report access. Ordinary readers receive read capability only.
2. Open the app's **Backend** dialog. Enter the backend root URL, label and audience
   `status`. Start from `deploy/connection-policy.json`. Replace port/network
   allowances with the exact destination needed by this deployment.
3. Generate a different random 32-byte signing key. The `keygen` command can write
   it to a separate file; do not reuse the storage key. Choose a key ID such as
   `status-2026-10`. Enter the base64 key and ID in the dialog. Leave the connection
   disabled during initial pairing and save.
4. Copy the displayed issuer, app ID, registration instance and audience into an
   owner-only pairing JSON file. Add the key ID and the same base64 signing key.
   Its complete shape is:

```json
{
  "issuer": "COPY_FROM_PORTAL",
  "audience": "status",
  "app_id": "status",
  "instance_id": "COPY_FROM_PORTAL",
  "key_id": "status-2026-10",
  "signing_key": "BASE64_32_BYTE_SIGNING_KEY"
}
```

5. Start the service with the actual paths:

```sh
./status serve \
  -listen :8791 \
  -database /srv/status/data/status.db \
  -storage-key-file /srv/status/secrets/status-storage.key \
  -pairing-file /srv/status/secrets/status-pairing.json
```

6. Verify `/healthz` and `/readyz` on the private service network. Enable the saved
   Portal connection only after checking the destination, pins, key and policy.
   Open `/apps/x/status` in Portal. A backend outage must show unavailable/unknown,
   never a green success state.

Only HTTPS is accepted by the recommended policy. For a private container network,
explicitly allow that network's CIDR and service port. Plain HTTP additionally
requires `plain_http: true` and is permitted only within an explicitly authorized
private network. Loopback, link-local and metadata targets remain forbidden. The
base URL has no credentials, query string, fragment or route path. The iframe
cannot select a different backend host.

## Configure components, credentials and grants

Open **Manage** inside the installed app. First save a credential of the matching
kind, then create a component and one or more monitors referencing it. Editing a
credential with blank secret fields preserves it. A read never returns the saved
secret. Deletion refuses while a monitor/publisher still references the credential.

Keep public labels distinct from internal labels. Components are private to
administrators until grants are configured. Load the current Portal user/OU
directory and select read grants. A user's current OU ancestor chain is resolved
by Portal on each call. A move, disable, expiry or session revocation applies to
the next request. Finance grants are separate and must be accompanied by read
access; public publication never grants finance access.

A component may contain several monitors. Omitted monitors are archived rather
than deleting retained observations or incident evidence. Disable a component to
archive it. Shared provider billing accounts should be represented by one balance
monitor/account component; do not create independent balance pools for each key.

Probe configuration:

| Kind | Credential fields | Configuration and meaning |
| --- | --- | --- |
| HTTP | Optional API key | Fixed URL, optional exact status/literal body condition, interval/timeout and explicit private CIDRs if necessary. Uses GET; no redirect following. |
| Dify | Application API key | Dify API root; authenticated GET `/v1/info`, no workflow execution or report generation. |
| PostgreSQL | Dedicated username/password | Host, port, database, explicit private CIDRs. Verified TLS and `SELECT 1`; mount a trusted CA through the normal system trust configuration if needed. |
| DeepSeek | API key | Account balance capability, selected currency and exact decimal low/recovery thresholds. Different currencies are never summed. |
| Qwen | Minimal RAM AccessKey ID/secret; optional STS token | Correct China/international billing site and currency. This reports cloud account credit/cash, not a model key's quota. |
| Heartbeat | At least 32 characters of signing secret | Interval defines the expected job cadence; see the signed ingress format below. |

HTTP checks optionally require one HTTP status (100–599) and/or a literal response
substring of at most 256 characters. Empty status requires any 2xx. The response is
bounded to 64 KiB; oversize/unreadable bodies are unknown, condition mismatches
are failures. Redirects and 429 responses remain unknown even if entered as an
expected status. Bodies are never stored or shown. These optional conditions
apply only to generic HTTP, preserving typed provider/Dify semantics.

Use **Billing account reference** for a stable local alias of the actual funding
account, such as `research-main`. It is required for saved DeepSeek/Qwen monitors;
use lowercase letters, numbers, dot, dash or underscore (1–64 characters). Verify
the actual account relationship before assigning aliases. Different keys do not
prove independent funding accounts. All active monitors for a provider/account
reference must belong to one component. Within that component, multiple currencies
are allowed, with one monitor per currency and one consistent billing site. They
remain distinct currencies, never a summed total. Reusing a credential under a
different account reference is refused. The alias stays in administrator-only
configuration and is not a public account identifier. Existing development billing
configurations need an alias saved before their next configuration update.

Defaults are 60-second checks and 300-second billing checks, with bounded jitter.
Intervals are 30 seconds–24 hours; timeouts are 1–15 seconds. A stale sample becomes
unknown after `max(3 * interval, 2 * timeout)`. Three failures confirm an ordinary
outage; two successes confirm recovery. Low funds use separate low/recovery
thresholds to avoid flapping. Review the final acceptance notes for remaining
measurement and historical-accounting limitations before production use.

The Alibaba billing permission is `bss:DescribeAcccount` (official spelling), with
resource `*`. Use a RAM identity limited to this action, not a main-account key.
Unsupported billing access, wrong site and malformed financial responses are not
reported as zero balance. Verify your account/site using a non-production identity
before enabling billing probes. References:
[balance operation](https://help.aliyun.com/en/user-center/developer-reference/api-bssopenapi-2017-12-14-queryaccountbalance),
[ACS3 signature](https://help.aliyun.com/zh/sdk/product-overview/v3-request-structure-and-signature).

To test saved configuration, open its component editor and choose **Request a
check** on the saved monitor. Unsaved edits are not sent. The action queues work;
it does not run a request in the browser or confirm recovery. It refuses stale
configuration revisions, disabled monitors/components, active leases, paused
probes and repeat requests within 30 seconds. Four workers and the per-credential
limit still apply. Refresh the overview for the actual observation.

After process interruption, an abandoned lease produces a persisted
`observer_unavailable` unknown observation at lease expiry. It does not count as
a target outage or a successful check. The scheduler postpones the retry by its
normal interval and jitter, and fresh confirmation is required for recovery.

## Read, search and export components

The private overview searches only currently visible component labels. Pages use
50 items by default and a maximum of 100; totals and search results are filtered
before pagination. A component detail request rechecks current OU/user authority,
including an old ID kept from an earlier page. Its monitor table shows last
successful observation, next scheduled check and latency without exposing target
addresses or stored credential references.

Open **Uptime history**, then **Export component JSON** to prepare one authorized
component snapshot plus its selected interval summary and coarse timeline. The
JSON has a version and generation time, uses the same current finance grant as
the UI, excludes configuration/credentials/internal evidence metadata, and is
bounded to 512 KiB. It appears in a read-only selectable text area for copying to
a local file, preserving the sandbox's existing download restrictions. An export
already copied outside the app is a local snapshot, not a live authorization view.

Private read views refresh every 30 seconds only while visible and idle. Admin
editors, active text fields and a prepared export do not get overwritten by a
background refresh. Backend scheduling continues with no browser open.

## Read history and coverage

The component overview includes a private hourly history strip and a version 2
uptime summary. Range boundaries are clipped to the actual requested interval,
monitor creation and the current time. Unobserved intervals and expired samples
are unknown. Paused periods and maintenance are excluded, with overlapping
windows counted once. Unknown and excluded time never increase healthy time.

`span_ms` covers the clipped range. `observed_ms` (also `coverage_ms`) equals
operational + degraded + outage time. `eligible_ms` is the same observed
denominator for availability; unknown and excluded time are separate. Always
show coverage beside availability: a short healthy sample does not establish
availability across a long unobserved range. Older observation records without
the versioned evidence metadata remain unknown at partial boundaries.

Hourly bars show the worst observed state in the clipped bucket, not an average:
outage, degraded, unknown, then operational. Public history requires both global
publication and component publication. Its DTO contains only interval boundaries
and a coarse state; no monitor identifiers, balances or private diagnostics.
The public page's observation timestamp is the actual oldest monitor observation,
while the page update timestamp only identifies when the response was generated.

Backups preserve evidence. Restore closes prior evidence at the restore instant,
then pauses probes and invalidates current state without rewriting earlier
intervals. Scheduling future maintenance does not reset existing observations.
Retrospective maintenance rebuilds affected intervals from retained raw evidence.
When that evidence has expired, maintenance exclusions remain exact and the rest
of a corrected bucket becomes unknown; the service never proportionally splits
an old aggregate. Raw evidence is read once per monitor for a correction range
and clipped per hour. Cleanup retains the hour overlapping the 90-day boundary.
An audited SLA claim still requires deployment-specific operational acceptance.

## Configure notification publication

Status does not send Email, Slack or Webhooks itself. Portal's notification system
owns the actual channels, templates and retries. In **Operations**, enter Portal's
HTTPS root and exact private CIDRs if applicable. Saving a changed destination
disables publisher configurations and marks old pending messages for review.

For each independently routed component:

1. Copy its opaque component ID from the app.
2. Create a dedicated Portal API token whose exact scope is
   `notify:status-<component-ID>`.
3. Save it in Status as a notification credential. Configure that component's
   publisher as `status-<component-ID>` and explicitly enable it.
4. In Portal notifications, create/review an exact event rule for
   `extension.service.status-<component-ID>.notice`. Choose the intended operator
   or OU recipients and destination channels.

Status checks the credential's actual publisher namespace through the read-only
`GET /api/v1/notifications/publisher` endpoint before POSTing any notice. A wrong
namespace is refused without sending. Read grants and notification recipients are
two separate administrator policies; update both when changing an audience.

Transition messages contain coarse status and opaque component identity. They do
not contain balances, targets or private diagnostics. A transition and its outbox
entry commit together. Retries keep identical payload and occurrence identity.
The default limit is five notices/component/hour; suppression is recorded in the
Status audit table. Portal's success response means durable capture, not that a
person received an Email, Slack message or Webhook. The app shows **Captured by
Portal** for this state.

Temporary preflight failures and HTTP 429/5xx remain retryable; failed credentials
or a mismatched publisher require review. Numeric/date `Retry-After` is honored,
bounded to one hour, alongside exponential retry delay. Provider 429 responses
also defer the next probe by the greater of its normal interval and the bounded
retry hint. A failed billing read or billing authentication failure remains
unknown, never a zero balance or a confirmed exhausted-credit result.

A timeout can be retried idempotently. A 409, wrong publisher, changed destination
or exhausted retry budget becomes **Review required**. Inspect the current queue,
verify any possible earlier Portal capture, then explicitly discard a notice or
retry with the same unchanged publisher. Never change an occurrence ID just to
bypass a conflict. Resume requires the displayed queue fingerprint to remain
unchanged since review.

## Signed heartbeat ingress

Allow only the relevant job network to reach:
`POST /ingest/v1/heartbeats/<monitor-ID>`.
Send a JSON object with an RFC3339 timestamp and a fresh nonce of 16–128 characters.
Set `X-Status-Signature` to the lowercase hex HMAC-SHA256 of these exact bytes:

```text
<monitor-ID>\n<exact JSON request body>
```

The key is that monitor's saved heartbeat signing secret. Use TLS at the ingress.
Do not send an API key in the URL or log the key/signature. Timestamps are accepted
within a narrow window and nonces are persisted as opaque observation identities;
a restart does not reset replay protection. There is a small per-monitor rate
ceiling. A successful POST means the heartbeat was captured, not that a backup is
valid or a downstream task succeeded.

## Private and optional public `/status`

The default gateway mode is a redirect using `deploy/nginx-private.conf`:
`/status` → `/apps/x/status`. Portal login and OU visibility still apply.

For a public page, explicitly enable public projection in Status Operations,
publish individual components with a public label, and separately publish each
incident's public narrative. Use `deploy/nginx-public.conf`, replacing its private
upstream. It exposes exact HTML/assets/public-read paths only. `/status/v1/*`,
private APIs and heartbeat ingress must remain unavailable through that location.
The assets and API URLs are relative and work below `/status/`.

Check the public page in a signed-out browser. Verify that no internal labels,
hostnames, database names, amounts, OU identities, provider IDs or private narrative
appear. The Status service can itself become unreachable; independent external
monitoring is required to detect that observer failure reliably.

## Anonymous request limits

Public assets and API requests share a bounded backend budget: 10 requests/second
per socket peer with a burst of 20, and 40 requests/second overall with a burst of
80. The peer registry holds at most 1,024 entries and evicts idle entries after a
minute when capacity is needed. Rejected requests return HTTP 429 with
`Retry-After: 1`. Health/readiness and authenticated routes do not consume this
anonymous budget. Existing total request concurrency limits still apply.

The backend deliberately ignores caller-supplied forwarding headers. When nginx
proxies all requests, its address is one peer; add a client-IP rate policy at the
trusted gateway for high-traffic publication. Do not enable arbitrary forwarded
header trust to obtain separate budgets. This is a bounded development service,
not a claim of an unmeasured public traffic capacity.

## Retention policy

In **Manage → Operations**, configure raw observations for 1–30 days (default 30)
and aggregate history/resolved incident families for a period from the raw
retention through 90 days (default 90). Saved values stay in Status storage.
Shortening retention authorizes background cleanup after the new cutoff; increase
it before cleanup if additional history must be retained. Raising the period
cannot recreate deleted evidence. Cleanup is bounded, preserves active incident
and unresolved notice evidence, and retains the hour overlapping the boundary.
The API accepts omitted/zero durations as preserving the current policy for older
clients; negative or out-of-range periods are refused.

Public component and incident lists also use 50-item pages with a 100 maximum.
Their counts contain only explicitly published components/narratives. Global
publication disabled returns no public counts or records.

## Backup, restore and rollback

Run offline backup commands with the same service account and encryption key.
Stop the service first: the volume lock deliberately prevents a second process
from opening the live database. Do not copy a SQLite file while its WAL is active.

```sh
./status backup \
  -database /srv/status/data/status.db \
  -storage-key-file /srv/status/secrets/status-storage.key \
  -file /srv/status/backups/status-before-upgrade.db
```

The output is a consistent SQLite snapshot and refuses to overwrite a file. Keep
it encrypted/protected with owner-only access. Store the storage key separately.
For restore, stop HTTP/workers and preserve the current data directory first:

```sh
./status restore \
  -database /srv/status/data/status.db \
  -storage-key-file /srv/status/secrets/status-storage.key \
  -file /srv/status/backups/status-before-upgrade.db
```

The command validates schema, references, integrity and key fingerprint into a
temporary file before replacement. It keeps `status.db.pre-restore` for rollback;
move that prior rollback copy to safe storage before another restore. A failed
validation preserves the live file. Do not run destructive down migrations.

Restore pauses probes and outbox, disables public output/publishers, clears leases
and makes started publications review-required. On restart, inspect the queue,
review publisher settings and possible earlier Portal captures, then resume using
the current fingerprint. Do not blindly replay a restored old snapshot.

A Portal restore separately clears pairing and rotates its registration instance.
Repeat pairing, review newly namespaced Status grants and reconfigure notification
routing. Normal signing-key rotation preserves the Portal connection's identity
seed; uninstall/reinstall or restore deliberately does not.

## Container template

`apps/status/Dockerfile` builds only the Status service and embeds its public
assets. `deploy/compose.yaml` is a local build template, not a published image.
Create its `data/` and `secrets/` directories with your service UID/GID and set
`STATUS_UID`, `STATUS_GID` and a private `STATUS_BIND_IP` deliberately. The default
loopback publish is for gateway access on the same host; Portal's backend
connection must use an approved private service address or verified HTTPS name.
The container runs without capabilities, with a read-only root filesystem and
only the independent data volume writable. Never mount the Docker socket or the
Portal database into it.
