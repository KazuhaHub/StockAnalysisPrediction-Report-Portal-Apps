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
