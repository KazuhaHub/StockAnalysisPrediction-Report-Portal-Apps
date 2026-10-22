# Request-bound extension identity protocol v1

This package is shared by the trusted Portal proxy and independent app backends.
It does not provide viewer lookup or replace a backend's component authorization.
The Portal must load current account/session/OU facts for every private request.

`X-Portal-Assertion` holds `base64url(JSON).base64url(HMAC-SHA256)`. The MAC input is
`rp-extension-v1` followed by a newline and the exact encoded JSON. A random
24-byte nonce, a 30-second lifetime, issuer, audience, app ID, registration instance,
key ID, viewer identity/current OU facts, normalized method/path/query and body
SHA-256 are authenticated together. GET requests sign an empty body.

Keys must contain at least 32 random bytes. They are stored sealed at the host and
provisioned into the intended backend via an operator-only secret mechanism.
Backends explicitly pin issuer/audience/app/registration and accepted key IDs.
Do not pass assertions or shared keys into iframe messages or logs. Transport uses
verified TLS unless an administrator explicitly approves a private connection.

Verification refuses unknown JSON fields, malformed encoding, wrong boundaries,
future issuance beyond five seconds, expiry, excessive lifetime and replay. The
bounded in-process nonce registry never evicts a live nonce; capacity exhaustion
fails closed. This is a single-process backend protocol. Restart/new registration
must rotate the registration ID/key before accepting traffic, since an in-memory
replay cache does not survive restart. A future distributed backend needs a shared
durable nonce store; it cannot silently reuse this process-local implementation.

Backend readiness must distinguish a generated new registration from the currently
approved one. After restore, all connections remain disabled until the operator
pairs the new instance/key. An assertion proves facts at its issue instant, not
indefinite access; backend authorization must use them only for the signed request.

Run `GOWORK=off go test -race ./...` and `GOWORK=off go vet ./...` in this directory.
Negative tests cover method/path/body/issuer/audience/app/instance/time/signature,
malformed input, replay concurrency and bounded capacity. Host-side tests must
add account/OU/session changes and app uninstall before the feature is complete.
