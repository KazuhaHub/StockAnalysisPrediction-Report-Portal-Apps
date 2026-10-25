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
    "16128f031fd71d83429db6a4209f8cfb02e5209b7c4f76a202c5dda1a00d929e",
  );
});
