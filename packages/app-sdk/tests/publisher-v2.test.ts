// @vitest-environment node
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import Ajv2020 from "ajv/dist/2020";
import {
  verifyPublisherDescriptor,
  descriptorSignatureInput,
  type PublisherTrust,
} from "../src/publisher-v2";
const fixture = readFileSync(
  new URL("./fixtures/publisher-signatures.json", import.meta.url),
);
const corpus = JSON.parse(fixture.toString()) as {
  frame_sha256: string;
  cases: {
    name: string;
    accept: boolean;
    descriptor_base64: string;
    envelope_base64: string;
    trust: PublisherTrust;
    now_ms: string;
  }[];
};
describe("shared publisher signature vectors", () => {
  it("keeps the exact shared refusal corpus", () => {
    expect(corpus.cases).toHaveLength(55);
    expect(createHash("sha256").update(fixture).digest("hex")).toBe(
      "f0553de5a701b0d8f665a2e997a525c8022ba5039ab6bce4c62da18f3118d641",
    );
  });
  for (const c of corpus.cases)
    it(c.name, async () => {
      const raw = Uint8Array.from(Buffer.from(c.descriptor_base64, "base64"));
      const envelope = Uint8Array.from(
        Buffer.from(c.envelope_base64, "base64"),
      );
      if (!c.accept) {
        await expect(
          verifyPublisherDescriptor(raw, envelope, c.trust, c.now_ms),
        ).rejects.toThrow("untrusted application descriptor");
        return;
      }
      const result = await verifyPublisherDescriptor(
        raw,
        envelope,
        c.trust,
        c.now_ms,
      );
      expect(result.descriptor.id).toBe("notes-sample");
      expect(result.keyID).toBe("test-key-1");
      expect(result.publisherRevision).toBe(c.trust.publishers[0].revision);
      expect(result.keyRevision).toBe(c.trust.publishers[0].keys[0].revision);
      expect(
        createHash("sha256")
          .update(descriptorSignatureInput(raw))
          .digest("hex"),
      ).toBe(corpus.frame_sha256);
    });
});

it("captures the exact bytes and policy revision before asynchronous crypto", async () => {
  const c = structuredClone(corpus.cases[0]);
  const raw = Uint8Array.from(Buffer.from(c.descriptor_base64, "base64"));
  const envelope = Uint8Array.from(Buffer.from(c.envelope_base64, "base64"));
  const pending = verifyPublisherDescriptor(raw, envelope, c.trust, c.now_ms);
  raw.fill(0);
  envelope.fill(0);
  c.trust.publishers[0].revision = "8";
  c.trust.publishers[0].keys[0].public_key = "AA";
  const result = await pending;
  expect(result.descriptor.id).toBe("notes-sample");
  expect(result.publisherRevision).toBe("7");
});

it("keeps the closed signature schema and positive vectors aligned", () => {
  const bytes = readFileSync(
    new URL("../schema/publisher-signature-v1.schema.json", import.meta.url),
  );
  expect(createHash("sha256").update(bytes).digest("hex")).toBe(
    "76fc2d3bb471e21934782dd2fbc7006bcbfc79068c087f6c48c645db9a6026f4",
  );
  const validate = new Ajv2020({ strict: true }).compile(
    JSON.parse(bytes.toString()),
  );
  for (const c of corpus.cases.filter((c) => c.accept))
    expect(
      validate(JSON.parse(Buffer.from(c.envelope_base64, "base64").toString())),
    ).toBe(true);
  const valid = JSON.parse(
    Buffer.from(corpus.cases[0].envelope_base64, "base64").toString(),
  );
  expect(validate({ ...valid, publisher: "example-publisher\n" })).toBe(false);
  expect(
    validate({
      ...valid,
      public_key: corpus.cases[0].trust.publishers[0].keys[0].public_key,
    }),
  ).toBe(false);
});

it("enforces publisher and namespace bounds independently of overlap", async () => {
  const c = corpus.cases[0];
  const raw = Uint8Array.from(Buffer.from(c.descriptor_base64, "base64"));
  const env = Uint8Array.from(Buffer.from(c.envelope_base64, "base64"));
  const verify = (trust: PublisherTrust) =>
    verifyPublisherDescriptor(raw, env, trust, c.now_ms);
  const trust = structuredClone(c.trust);
  for (let i = 1; i < 128; i++)
    trust.publishers.push({
      id: `bounded-${i}`,
      revision: "1",
      enabled: false,
      namespaces: [],
      keys: [],
    });
  await expect(verify(trust)).resolves.toHaveProperty("keyID", "test-key-1");
  trust.publishers.push({
    id: "overflow",
    revision: "1",
    enabled: false,
    namespaces: [],
    keys: [],
  });
  await expect(verify(trust)).rejects.toThrow();
  const namespaces = structuredClone(c.trust);
  for (let i = 0; i < 4; i++)
    namespaces.publishers.push({
      id: `bounded-${i}`,
      revision: "1",
      enabled: false,
      namespaces: Array.from({ length: 64 }, (_, j) => ({
        kind: "exact",
        value: `owned-${i}-${j}`,
      })),
      keys: [],
    });
  const last = namespaces.publishers.at(-1)!;
  const extra = last.namespaces.pop()!;
  await expect(verify(namespaces)).resolves.toHaveProperty(
    "keyID",
    "test-key-1",
  );
  last.namespaces.push(extra);
  await expect(verify(namespaces)).rejects.toThrow();
  const perPublisher = structuredClone(c.trust);
  for (let i = 0; i < 64; i++)
    perPublisher.publishers[0].namespaces.push({
      kind: "exact",
      value: `owned-${i}`,
    });
  await expect(verify(perPublisher)).rejects.toThrow();
});
