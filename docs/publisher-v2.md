# Experimental publisher verification

`@portal-app/sdk/publisher-v2` is authoring/preflight infrastructure. It is not an
app permission, publisher enrollment API, installer or stable public contract.
Existing installed apps and the legacy SDK entry remain unchanged.

```ts
import { verifyPublisherDescriptor } from '@portal-app/sdk/publisher-v2';

const result = await verifyPublisherDescriptor(
  descriptorBytes,
  detachedSignatureBytes,
  currentDeploymentTrustSnapshot,
  currentUTCMillisecondsAsDecimalString,
);
```

Supply the exact downloaded UTF-8 descriptor/envelope bytes as `Uint8Array`s.
The host supplies trust; a package, catalogue or frontend cannot enroll its own
key. Ed25519 verification runs through Web Crypto. Unsupported cryptographic
providers refuse verification; there is no weaker algorithm fallback.

The host must independently verify and recheck current trust and revisions at
activation commit. An SDK result in an untrusted app never authorizes execution.
The helper performs no fetch, storage, enrollment or lifecycle operation.
Invalid input throws `PublisherVerificationError` with fixed safe text.

See the [complete Portal contract](https://github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal/blob/kazuha/app-publisher-verification/docs/app-platform/24-publisher-signature-verification.md)
for exact framing, envelope fields, trust bounds and remaining admission work.
The copied schema is available under `@portal-app/sdk/publisher-signature-v1.schema.json`;
a JSON Schema check does not replace the strict byte parser or cryptography.

The development corpus has 55 shared Go/TypeScript cases and exact SHA-256
`f0553de5a701b0d8f665a2e997a525c8022ba5039ab6bce4c62da18f3118d641`.
Its RFC 8032 test key is public test material; never enroll it in a deployment.
The signature schema is separately pinned to SHA-256
`76fc2d3bb471e21934782dd2fbc7006bcbfc79068c087f6c48c645db9a6026f4`.
Changing these files requires deliberate review and synchronized tests in both
repositories, not silent regeneration in an application's build.

Run `npm run test:sdk` and `npm run typecheck` from the repository root.

## Signing a descriptor

`packages/extensionprotocol/cmd/portal-sign-descriptor` is a Go command that creates a
publisher signing key and produces, and checks, the `descriptor.sig` that
`scripts/pack-offline-envelope.py` packs and the Portal verifies. It enrolls
nothing: trust is granted by a Portal administrator.

Run it from `packages/extensionprotocol` (`go run ./cmd/portal-sign-descriptor ...`)
or build it once with `go build -o portal-sign-descriptor ./cmd/portal-sign-descriptor`.

1. **Create a key pair, once per signing key.** Keep the private key outside this
   repository, for example in `~/.config/portal-publisher/`.

   ```sh
   portal-sign-descriptor keygen --key-id release-2026 \
     --private-key ~/.config/portal-publisher/release-2026.key
   ```

   The private key file is created with mode 0600 and the command refuses to
   overwrite an existing file. The command prints the key ID, the public key (43
   characters, unpadded base64url), the SHA-256 of the raw public key, and the key
   object the administrator needs. The private key is never printed. Back it up:
   losing it means rotating to a new key.

2. **Enroll the public key in the Portal.** Send the key ID, the public key and the
   SHA-256 through a channel the administrator trusts independently of the package.
   In the Portal an administrator opens Manage, Publishers
   (`POST /api/admin/app-platform/publishers`) and either registers the publisher
   with its application ID scopes and this key (`register`), or adds it to an
   existing publisher (`add_key`). The `publisher` field of your descriptor must be
   that registered publisher ID and the app ID must fall inside its scopes. Nothing
   below works until this is done.

3. **Build the unsigned candidate.**

   ```sh
   python3 scripts/build-app-v2.py my-app --output .development/candidate
   ```

   Add `--images .development/image/images.json` for an app with a managed backend,
   as described in the plugin development standard.

4. **Sign the exact descriptor bytes.** Any later change to `descriptor.json`, even
   a newline, invalidates the signature; sign last.

   ```sh
   portal-sign-descriptor sign \
     --descriptor .development/candidate/descriptor.json \
     --private-key ~/.config/portal-publisher/release-2026.key \
     --key-id release-2026 --out descriptor.sig
   portal-sign-descriptor verify \
     --descriptor .development/candidate/descriptor.json \
     --signature descriptor.sig --public-key <public key from step 1>
   ```

   `sign` refuses a private key file readable by group or others, a descriptor that
   is not a strict `portal.app/v2` JSON object (duplicate keys, a byte order mark,
   trailing data, a missing or invalid publisher), and an output file that already
   exists. It checks only what the signature depends on; the full descriptor
   validation is `build-app-v2.py`, `pack-offline-envelope.py` and the Portal.
   `verify` checks the strict envelope, that it names this descriptor's publisher and
   digest, optionally the key ID (`--key-id`), and the Ed25519 signature. It does
   not check trust, namespaces or key validity; only the Portal does that.

5. **Pack the envelope.**

   ```sh
   python3 scripts/pack-offline-envelope.py \
     --descriptor .development/candidate/descriptor.json --signature descriptor.sig \
     --frontend .development/candidate/frontend.zip --output my-app.portalapp
   ```

   Add `--image-blobs .development/image/blobs` for a managed backend. Install the
   `.portalapp` through the Portal; the Portal verifies the signature against the
   enrolled key at install time.

The signature is Ed25519 over `"portal.app/descriptor/v2" || 0x00 || uint64_be(len) ||
descriptor bytes`. `descriptor.sig` is the compact JSON envelope
`portal.app.signature/1-dev.1` described above. The tool's tests reproduce the Portal's
shared corpus envelope byte for byte from the RFC 8032 test key (never enroll that key).

To rotate, create a new key with a new key ID, have the administrator `add_key` it,
sign new releases with it, then have the old key revoked. A key ID is never reused.
