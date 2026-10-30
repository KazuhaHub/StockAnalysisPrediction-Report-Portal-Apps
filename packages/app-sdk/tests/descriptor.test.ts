import { createHash } from "node:crypto";
import { Buffer } from "node:buffer";
import { TextDecoder, TextEncoder } from "node:util";
import { afterEach, expect, test, vi } from "vitest";
import corpus from "./fixtures/descriptor-v2.json";
import corpusBytes from "./fixtures/descriptor-v2.json?raw";
import {
  DescriptorError,
  parseDescriptor,
  MAX_DESCRIPTOR_BYTES,
} from "../src/descriptor-v2";

afterEach(() => vi.unstubAllGlobals());

function encoding() {
  vi.stubGlobal("TextDecoder", TextDecoder);
  vi.stubGlobal("TextEncoder", TextEncoder);
}

for (const item of corpus.cases) {
  test(`shared descriptor corpus: ${item.name}`, () => {
    encoding();
    const input = new Uint8Array(Buffer.from(item.input_base64, "base64"));
    if (item.valid) expect(parseDescriptor(input).id).toBe("notes-sample");
    else expect(() => parseDescriptor(input)).toThrow(DescriptorError);
  });
}

test("oversized input fails with a bounded safe error", () => {
  encoding();
  expect(() =>
    parseDescriptor(new Uint8Array(MAX_DESCRIPTOR_BYTES + 1)),
  ).toThrow("invalid application descriptor");
});

test("shared corpus bytes match the host contract revision", () => {
  const bytes = corpusBytes;
  expect(createHash("sha256").update(bytes).digest("hex")).toBe(
    "fd840edca492f2e0a1ffab89b13ae0da8c626ccd7a24860f8b7f1c8a0c39e3ec",
  );
});
