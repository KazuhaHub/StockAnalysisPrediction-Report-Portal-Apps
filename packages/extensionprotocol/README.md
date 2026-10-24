# Request-bound extension identity protocol v1

This package is shared by the trusted Portal proxy and independent app backends.
It does not provide viewer lookup or replace a backend's component authorization.
The Portal must load current account/session/OU facts for every private request.

`X-Portal-Assertion` holds `base64url(JSON).base64url(HMAC-SHA256)`. The MAC input is
`rp-extension-v1` followed by a newline and the exact encoded JSON. A random
24-byte nonce, a 30-second lifetime, issuer, audience, app ID, registration instance,
key ID, backend boot ID, viewer identity/current OU facts, normalized method/path/query and body
SHA-256 are authenticated together. GET requests sign an empty body.

Keys must contain at least 32 random bytes. They are stored sealed at the host and
provisioned into the intended backend via an operator-only secret mechanism.
Backends explicitly pin issuer/audience/app/registration and accepted key IDs.
Do not pass assertions or shared keys into iframe messages or logs. Transport uses
verified TLS unless an administrator explicitly approves a private connection.

Verification refuses unknown JSON fields, malformed encoding, wrong boundaries,
future issuance beyond five seconds, expiry, excessive lifetime and replay. The
bounded in-process nonce registry never evicts a live nonce; capacity exhaustion
fails closed. This is a single-process backend protocol. Each backend startup
creates a fresh unpredictable boot ID, pinned by its verifier; old-boot assertions
are refused even though the replay cache is empty. The host obtains that boot ID
using `NewChallenge`/`AnswerChallenge`/`VerifyAnswer`, proving the same fixed key,
registration, audience and fresh request nonce in both directions. A replayed answer
for another challenge is refused. The boot ID is transient and is not an ACL grant
or registration ID. Restore still disables the host connection until operator review.
A future distributed backend needs a shared nonce store or independent per-replica
boot routing; it cannot silently reuse this process-local implementation.

An assertion proves facts at its issue instant, not
indefinite access; backend authorization must use them only for the signed request.

Run `GOWORK=off go test -race ./...` and `GOWORK=off go vet ./...` in this directory.
Negative tests cover method/path/body/issuer/audience/app/instance/time/signature,
malformed input, replay concurrency and bounded capacity. Host-side tests must
add account/OU/session changes and app uninstall before the feature is complete.


`Policy` and `BackendClient` implement segment-boundary route allowlists,
connection-specific private networks/ports, DNS validation at dial time and address
pinning. Local/link-local/metadata and translation/tunnel ranges are refused even
under a broad private-network rule. Plain HTTP requires an explicit private-network
policy and cannot send assertions to public addresses. Redirects, oversized headers,
oversized bodies and malformed/non-JSON responses are refused. Per-client calls are
bounded at two with a 15-second full deadline; the host must add its separate global
bound when wiring the proxy. No incoming cookies/headers are forwarded.
