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

function managedDescriptor(change: (backend: Record<string, unknown>) => void) {
  const found = corpus.cases.find((item) => {
    if (!item.valid) return false;
    const value = JSON.parse(
      Buffer.from(item.input_base64, "base64").toString(),
    );
    return value.backend != null;
  });
  const value = JSON.parse(
    Buffer.from(found!.input_base64, "base64").toString(),
  );
  const entry = (platform: string) => ({
    platform,
    manifest_digest: "a".repeat(64),
    config_digest: "b".repeat(64),
    layers: [{ diff_id: "c".repeat(64), uncompressed_bytes: 10 }],
  });
  delete value.backend.image;
  value.backend.images = [entry("linux/amd64"), entry("linux/arm64")];
  change(value.backend);
  return new Uint8Array(Buffer.from(JSON.stringify(value)));
}

test("managed backend images are accepted once per declared platform", () => {
  encoding();
  expect(
    parseDescriptor(managedDescriptor(() => {})).backend?.images,
  ).toHaveLength(2);
});

test("managed backend images refuse loose forms", () => {
  encoding();
  const refused: Array<(b: Record<string, unknown>) => void> = [
    (b) => (b.image = "ghcr.io/example/x@sha256:" + "b".repeat(64)),
    (b) => delete b.images,
    (b) => (b.images as unknown[]).pop(),
    (b) => ((b.images as { platform: string }[])[1].platform = "linux/amd64"),
    (b) => (b.platforms = ["linux/amd64"]),
    (b) => ((b.images as { layers: unknown[] }[])[0].layers = []),
    (b) =>
      ((
        b.images as { layers: { uncompressed_bytes: number }[] }[]
      )[0].layers[0].uncompressed_bytes = 0),
    (b) =>
      ((b.images as { manifest_digest: string }[])[0].manifest_digest =
        "sha256:x"),
    (b) => ((b.images as Record<string, unknown>[])[0].extra = 1),
  ];
  for (const change of refused)
    expect(() => parseDescriptor(managedDescriptor(change))).toThrow(
      DescriptorError,
    );
});
