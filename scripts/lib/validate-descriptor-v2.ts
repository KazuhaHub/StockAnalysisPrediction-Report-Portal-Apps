import { readFileSync, statSync } from "node:fs";
import {
  parseDescriptor,
  MAX_DESCRIPTOR_BYTES,
} from "../../packages/app-sdk/src/descriptor-v2";
try {
  const path = process.argv[2];
  if (!path || statSync(path).size > MAX_DESCRIPTOR_BYTES) throw new Error();
  parseDescriptor(new Uint8Array(readFileSync(path)));
} catch {
  console.error("Application descriptor preflight refused");
  process.exitCode = 1;
}
