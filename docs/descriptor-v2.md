# Experimental v2 descriptor validation

This implements a P02 declaration parser for the
[application platform plan](https://github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal/tree/main/docs/app-platform).
It is not the legacy `app.json` format, an application installer, a publisher
verification service or a production-admitted package contract. The existing
market and installed applications are unchanged.

```ts
import { parseDescriptor } from '@portal-app/sdk/descriptor-v2';

const declaration = parseDescriptor(descriptorBytes);
```

`descriptorBytes` is a `Uint8Array` of the exact UTF-8 descriptor file. Successful
parsing returns typed declarations. Invalid input throws a bounded `DescriptorError`
with no upstream text. No network, file access, browser state or execution occurs.
The subpath is experimental and is not re-exported through the legacy SDK entry.

Required later gates remain separate:

- Trusted publisher/signature/namespace and revocation verification.
- Exact artifact checksum and image-platform verification.
- Actual compatibility range evaluation, rather than bounded range text.
- Current administrator review and effective capability/resource admission.
- Runtime isolation, data compatibility and lifecycle execution.

Never use the return value as proof that code can run, that a capability was
granted or that a descriptor has a valid signature. The host binds signatures and
review identity to the original bytes, not a reserialized JavaScript object.

## Shared corpus and semantics

Portal's Go parser and this parser share a 44-case byte corpus. Both tests pin its
SHA-256 to `16128f031fd71d83429db6a4209f8cfb02e5209b7c4f76a202c5dda1a00d929e`.
The files are pinned to LF in Git so Windows checkout conversion does not change
that revision. Updating the corpus requires updating both repositories and their
documented acceptance results; a changed test fixture is not a protocol release.

Cases include static/managed descriptors, whitespace, duplicate/escaped duplicate
keys, case aliases, unknown fields, forbidden paths, mutable images, malformed
resources, capability dependencies, locales, data schemas and invalid UTF-8/BOM.
Optional null/omitted fields preserve the Go declaration interpretation where
they do not grant authority. Integer declarations reject decimal and exponent
lexemes, including `64.0`, to match the Go typed JSON parser.

The scanner checks every object before `JSON.parse`, which would otherwise discard
duplicate keys. A fatal UTF-8 decoder prevents replacement of malformed bytes.
Nesting and input size are bounded before typed validation. SDK field validation
does not freeze the future schema: D3 review and broader generated-schema parity
are still required.

## Development verification

From the Apps repository root:

```sh
npm run test:sdk
npm run typecheck
python3 scripts/plugin-standard.py
python3 scripts/test-app-template.py
```

The parser adds no package dependency and does not import React. Its test-only
Node APIs read/hash the fixed public corpus; they are not bundled into app code.
Existing Status/demo/template regressions remain required for SDK changes.
