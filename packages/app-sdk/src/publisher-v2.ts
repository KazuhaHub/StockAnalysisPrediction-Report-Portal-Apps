import { parseDescriptor, type Descriptor } from "./descriptor-v2";
export interface PublisherNamespace {
  kind: "exact" | "prefix";
  value: string;
}
export interface PublisherKey {
  id: string;
  algorithm: string;
  public_key: string;
  not_before_ms: string;
  not_after_ms: string | null;
  revoked_ms: string | null;
  revision: string;
}
export interface TrustedPublisher {
  id: string;
  enabled: boolean;
  revision: string;
  namespaces: PublisherNamespace[];
  keys: PublisherKey[];
}
export interface PublisherTrust {
  publishers: TrustedPublisher[];
}
export interface VerifiedPublisherDescriptor {
  descriptor: Descriptor;
  descriptorSHA256: string;
  keyID: string;
  publisherRevision: string;
  keyRevision: string;
}

export class PublisherVerificationError extends Error {
  constructor() {
    super("untrusted application descriptor");
    this.name = "PublisherVerificationError";
  }
}
const fields = [
  "format",
  "algorithm",
  "publisher",
  "key_id",
  "descriptor_sha256",
  "signature",
] as const;
const slug = /^[a-z][a-z0-9-]{0,63}$/;
const keyID = /^[a-z0-9][a-z0-9._-]{0,127}$/;
const digest = /^[a-f0-9]{64}$/;
const fail = (): never => {
  throw new PublisherVerificationError();
};
function match(value: unknown, re: RegExp): value is string {
  return typeof value === "string" && re.exec(value)?.[0] === value;
}
function counter(value: unknown, positive = false): bigint {
  if (!match(value, /^(0|[1-9][0-9]{0,18})$/)) return fail();
  const n = BigInt(value);
  if (n > 9223372036854775807n || (positive && n === 0n)) return fail();
  return n;
}
function decode64(value: unknown, size: number): Uint8Array<ArrayBuffer> {
  if (
    typeof value !== "string" ||
    value.length !== Math.ceil((size * 8) / 6) ||
    !match(value, /^[A-Za-z0-9_-]+$/)
  )
    return fail();
  const bytes = Uint8Array.from(
    atob(
      value.replace(/-/g, "+").replace(/_/g, "/") +
        "=".repeat((4 - (value.length % 4)) % 4),
    ),
    (c) => c.charCodeAt(0),
  );
  const encoded = btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
  if (bytes.length !== size || encoded !== value) return fail();
  return bytes;
}
function contains(ns: PublisherNamespace, id: string): boolean {
  return ns.kind === "exact" ? ns.value === id : id.startsWith(ns.value);
}
function overlap(a: PublisherNamespace, b: PublisherNamespace): boolean {
  if (a.kind === "exact") return contains(b, a.value);
  if (b.kind === "exact") return contains(a, b.value);
  return a.value.startsWith(b.value) || b.value.startsWith(a.value);
}
function validateTrust(trust: PublisherTrust): void {
  if (
    !trust ||
    !Array.isArray(trust.publishers) ||
    trust.publishers.length > 128
  )
    fail();
  const publishers = new Set<string>(),
    namespaces: PublisherNamespace[] = [];
  let keys = 0;
  for (const p of trust.publishers) {
    if (
      !p ||
      !match(p.id, slug) ||
      publishers.has(p.id) ||
      typeof p.enabled !== "boolean" ||
      !Array.isArray(p.namespaces) ||
      p.namespaces.length > 64 ||
      !Array.isArray(p.keys)
    )
      fail();
    counter(p.revision, true);
    publishers.add(p.id);
    for (const ns of p.namespaces) {
      if (
        !ns ||
        !(
          (ns.kind === "exact" && match(ns.value, slug)) ||
          (ns.kind === "prefix" &&
            typeof ns.value === "string" &&
            ns.value.length <= 64 &&
            ns.value.endsWith("-") &&
            match(ns.value.slice(0, -1), slug))
        )
      )
        fail();
      if (
        namespaces.length >= 256 ||
        namespaces.some((previous) => overlap(ns, previous))
      )
        fail();
      namespaces.push(ns);
    }
    keys += p.keys.length;
    if (keys > 256) fail();
    const ids = new Set<string>();
    for (const key of p.keys) {
      if (
        !key ||
        !match(key.id, keyID) ||
        ids.has(key.id) ||
        key.algorithm !== "Ed25519"
      )
        fail();
      ids.add(key.id);
      const before = counter(key.not_before_ms);
      counter(key.revision, true);
      decode64(key.public_key, 32);
      if (key.not_after_ms !== null && counter(key.not_after_ms) <= before)
        fail();
      if (key.revoked_ms !== null) counter(key.revoked_ms);
    }
  }
}

// A small closed flat-string grammar preserves duplicate keys before JSON.parse.
// No generic JSON object supplied by an app can choose a trust key or algorithm.
function parseEnvelope(
  raw: Uint8Array,
): Record<(typeof fields)[number], string> {
  if (raw.length === 0 || raw.length > 4096) fail();
  const text = new TextDecoder("utf-8", {
    fatal: true,
    ignoreBOM: true,
  }).decode(raw);
  let at = 0;
  const skip = () => {
    while (/[\x20\t\r\n]/.test(text[at] ?? "\0")) at++;
  };
  const stringToken =
    /"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"/y;
  const string = (): string => {
    stringToken.lastIndex = at;
    const token = stringToken.exec(text);
    if (!token) return fail();
    at = stringToken.lastIndex;
    return JSON.parse(token[0]) as string;
  };
  const result: Record<string, string> = Object.create(null) as Record<
    string,
    string
  >;
  skip();
  if (text[at++] !== "{") fail();
  for (let i = 0; i < fields.length; i++) {
    skip();
    const key = string();
    if (
      !fields.includes(key as (typeof fields)[number]) ||
      Object.hasOwn(result, key)
    )
      fail();
    skip();
    if (text[at++] !== ":") fail();
    skip();
    result[key] = string();
    skip();
    if (text[at++] !== (i === fields.length - 1 ? "}" : ",")) fail();
  }
  skip();
  if (
    at !== text.length ||
    result.format !== "portal.app.signature/1-dev.1" ||
    result.algorithm !== "Ed25519" ||
    !match(result.publisher, slug) ||
    !match(result.key_id, keyID) ||
    !match(result.descriptor_sha256, digest)
  )
    fail();
  decode64(result.signature, 64);
  return result as Record<(typeof fields)[number], string>;
}

// Experimental publisher-tool framing, not an execution authorization token.
export function descriptorSignatureInput(
  raw: Uint8Array,
): Uint8Array<ArrayBuffer> {
  if (raw.byteLength === 0 || raw.byteLength > 131072) fail();
  const prefix = new TextEncoder().encode("portal.app/descriptor/v2\0");
  const frame = new Uint8Array(prefix.length + 8 + raw.length);
  frame.set(prefix);
  new DataView(frame.buffer).setBigUint64(
    prefix.length,
    BigInt(raw.length),
    false,
  );
  frame.set(raw, prefix.length + 8);
  return frame;
}

// Host-authoritative current trust is required. A verified copy in an app cannot
// enroll a publisher, authorize installation or replace the host's commit check.
export async function verifyPublisherDescriptor(
  raw: Uint8Array,
  envelope: Uint8Array,
  trust: PublisherTrust,
  nowMS: string,
): Promise<VerifiedPublisherDescriptor> {
  try {
    if (
      raw.byteLength === 0 ||
      raw.byteLength > 131072 ||
      envelope.byteLength === 0 ||
      envelope.byteLength > 4096
    )
      fail();
    const now = counter(nowMS);
    validateTrust(trust);
    // Copy bytes and capture all policy inputs before the first asynchronous call.
    const bytes = Uint8Array.from(raw),
      detached = parseEnvelope(Uint8Array.from(envelope));
    const descriptor = parseDescriptor(bytes);
    if (descriptor.publisher !== detached.publisher) fail();
    const publisher = trust.publishers.find((p) => p.id === detached.publisher);
    if (
      !publisher?.enabled ||
      !publisher.namespaces.some((ns) => contains(ns, descriptor.id))
    )
      return fail();
    const key = publisher.keys.find((k) => k.id === detached.key_id);
    if (
      !key ||
      key.revoked_ms !== null ||
      now < counter(key.not_before_ms) ||
      (key.not_after_ms !== null && now >= counter(key.not_after_ms))
    )
      return fail();
    const publicBytes = decode64(key.public_key, 32),
      signature = decode64(detached.signature, 64);
    const identity = {
      keyID: key.id,
      publisherRevision: publisher.revision,
      keyRevision: key.revision,
    };
    const descriptorSHA256 = Array.from(
      new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
      (v) => v.toString(16).padStart(2, "0"),
    ).join("");
    if (descriptorSHA256 !== detached.descriptor_sha256) return fail();
    const publicKey = await crypto.subtle.importKey(
      "raw",
      publicBytes,
      { name: "Ed25519" },
      false,
      ["verify"],
    );
    if (
      !(await crypto.subtle.verify(
        "Ed25519",
        publicKey,
        signature,
        descriptorSignatureInput(bytes),
      ))
    )
      return fail();
    return Object.freeze({ descriptor, descriptorSHA256, ...identity });
  } catch {
    return fail();
  }
}
