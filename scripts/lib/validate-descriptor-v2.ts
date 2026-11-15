import { readFileSync, statSync } from "node:fs";
import { createHash } from "node:crypto";
import {
  parseDescriptor,
  MAX_DESCRIPTOR_BYTES,
} from "../../packages/app-sdk/src/descriptor-v2";

const corpusSHA256 =
  "fd840edca492f2e0a1ffab89b13ae0da8c626ccd7a24860f8b7f1c8a0c39e3ec";

function checkCorpus(path: string) {
  if (statSync(path).size > 16 << 20) throw new Error();
  const raw = readFileSync(path);
  if (createHash("sha256").update(raw).digest("hex") !== corpusSHA256)
    throw new Error();
  const corpus: unknown = JSON.parse(raw.toString("utf8"));
  if (
    corpus == null ||
    typeof corpus !== "object" ||
    !Array.isArray((corpus as { cases?: unknown }).cases) ||
    (corpus as { cases: unknown[] }).cases.length !== 56
  )
    throw new Error();
  for (const value of (corpus as { cases: unknown[] }).cases) {
    if (value == null || typeof value !== "object") throw new Error();
    const item = value as {
      name?: unknown;
      valid?: unknown;
      input_base64?: unknown;
    };
    if (
      typeof item.name !== "string" ||
      typeof item.valid !== "boolean" ||
      typeof item.input_base64 !== "string"
    )
      throw new Error();
    const encoded = item.input_base64;
    const bytes = Buffer.from(encoded, "base64");
    if (bytes.toString("base64") !== encoded) throw new Error();
    let valid = true;
    try {
      parseDescriptor(new Uint8Array(bytes));
    } catch {
      valid = false;
    }
    if (valid !== item.valid) throw new Error(item.name);
  }
  console.log("Validated 56 shared descriptor corpus cases.");
}

try {
  const args = process.argv.slice(2);
  if (args.length === 2 && args[0] === "--corpus") {
    checkCorpus(args[1]);
  } else if (args.length === 1) {
    const path = args[0];
    if (statSync(path).size > MAX_DESCRIPTOR_BYTES) throw new Error();
    parseDescriptor(new Uint8Array(readFileSync(path)));
  } else {
    throw new Error();
  }
} catch {
  console.error("Application descriptor preflight refused");
  process.exitCode = 1;
}
