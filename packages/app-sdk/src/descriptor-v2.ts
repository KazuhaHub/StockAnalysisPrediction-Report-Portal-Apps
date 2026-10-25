// Experimental declaration validation only. This does not verify signatures,
// compatibility, artifact bytes, effective permissions or runtime admission.
export const MAX_DESCRIPTOR_BYTES = 128 << 10;

export class DescriptorError extends Error {
  constructor() {
    super("invalid application descriptor");
    this.name = "DescriptorError";
  }
}

export interface Descriptor {
  format: "portal.app/v2";
  id: string;
  version: string;
  publisher: string;
  compatibility: { platform_api: string; runner_protocol: string };
  presentation: {
    name_key: string;
    description_key: string;
    entry: string;
    locales: string[];
    routes: { id: string; path: string; layout: "document" | "viewport" }[];
  };
  frontend: { artifact: string; sha256: string };
  backend?: {
    kind: "oci";
    image: string;
    platforms: string[];
    protocol: "portal.backend/1";
    resources: { memory_mib: number; cpu_millis: number; pids: number };
  } | null;
  capabilities?: {
    required?: string[] | null;
    optional?: string[] | null;
  } | null;
  data: {
    schema: number;
    readable_schemas: number[];
    writes_on_startup?: false | null;
  };
}

const slug = /^[a-z][a-z0-9-]{0,63}$/;
const copyKey = /^[a-z][a-z0-9_.-]{0,95}$/;
const digest = /^[a-f0-9]{64}$/;
const range = /^[0-9A-Za-z.*+<>=~^| -]{1,96}$/;
const version =
  /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?(\+[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$/;
const image =
  /^[a-z0-9][a-z0-9.-]*(:[0-9]{1,5})?\/[a-z0-9][a-z0-9._/-]*@sha256:[a-f0-9]{64}$/;
const known = new Set([
  "reports.read",
  "storage.files",
  "tasks.schedule",
  "events.subscribe",
  "notifications.publish",
  "network.http",
  "network.stream",
  "secrets.use",
  "secrets.read",
  "background.run",
  "files.export",
]);

function match(value: unknown, pattern: RegExp, max = 512): value is string {
  return (
    typeof value === "string" &&
    value.length <= max &&
    pattern.exec(value)?.[0] === value
  );
}
function record(
  value: unknown,
  keys: string[],
): value is Record<string, unknown> {
  return (
    value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value).every((key) => keys.includes(key))
  );
}
function integer(value: unknown, min: number, max: number): value is number {
  return (
    typeof value === "number" &&
    Number.isSafeInteger(value) &&
    value >= min &&
    value <= max
  );
}
function unique(values: unknown, allowed: string[]): values is string[] {
  return (
    Array.isArray(values) &&
    values.length > 0 &&
    values.length <= allowed.length &&
    new Set(values).size === values.length &&
    values.every((v) => typeof v === "string" && allowed.includes(v))
  );
}
function safePath(value: unknown): value is string {
  return (
    match(value, /^[a-zA-Z0-9._/-]+$/, 256) &&
    !value.startsWith("/") &&
    !value.includes("..") &&
    value.split("/").every((segment) => segment !== "" && segment !== ".")
  );
}
function validVersion(value: unknown): boolean {
  if (!match(value, version, 128)) return false;
  const withoutBuild = value.split("+", 1)[0];
  const separator = withoutBuild.indexOf("-");
  return (
    separator < 0 ||
    withoutBuild
      .slice(separator + 1)
      .split(".")
      .every(
        (part) =>
          !(part.length > 1 && part[0] === "0" && /^[0-9]+$/.test(part)),
      )
  );
}
function validBackend(value: unknown): boolean {
  if (
    !record(value, ["kind", "image", "platforms", "protocol", "resources"]) ||
    value.kind !== "oci" ||
    value.protocol !== "portal.backend/1" ||
    !match(value.image, image) ||
    value.image.includes("..") ||
    value.image.includes("//") ||
    !unique(value.platforms, ["linux/amd64", "linux/arm64"])
  )
    return false;
  const r = value.resources;
  return (
    record(r, ["memory_mib", "cpu_millis", "pids"]) &&
    integer(r.memory_mib, 16, 4096) &&
    integer(r.cpu_millis, 25, 4000) &&
    integer(r.pids, 16, 1024)
  );
}
function validCapabilities(value: unknown, backend: boolean): boolean {
  if (value === undefined || value === null) value = {};
  if (!record(value, ["required", "optional"])) return false;
  const required = value.required ?? [],
    optional = value.optional ?? [];
  if (!Array.isArray(required) || !Array.isArray(optional)) return false;
  const both = [...required, ...optional];
  if (
    new Set(both).size !== both.length ||
    !both.every((v) => typeof v === "string" && known.has(v))
  )
    return false;
  for (const name of ["tasks.schedule", "events.subscribe", "background.run"])
    if (both.includes(name) && !backend) return false;
  for (const name of ["tasks.schedule", "events.subscribe"]) {
    if (both.includes(name) && !both.includes("background.run")) return false;
    if (required.includes(name) && !required.includes("background.run"))
      return false;
  }
  return true;
}
function validManifest(value: unknown): value is Descriptor {
  if (
    !record(value, [
      "format",
      "id",
      "version",
      "publisher",
      "compatibility",
      "presentation",
      "frontend",
      "backend",
      "capabilities",
      "data",
    ]) ||
    value.format !== "portal.app/v2" ||
    !match(value.id, slug) ||
    !match(value.publisher, slug) ||
    !validVersion(value.version)
  )
    return false;
  const c = value.compatibility;
  if (
    !record(c, ["platform_api", "runner_protocol"]) ||
    !match(c.platform_api, range) ||
    !match(c.runner_protocol, range) ||
    !c.platform_api.trim() ||
    !c.runner_protocol.trim()
  )
    return false;
  const p = value.presentation;
  if (
    !record(p, ["name_key", "description_key", "entry", "locales", "routes"]) ||
    !match(p.name_key, copyKey) ||
    !match(p.description_key, copyKey) ||
    !safePath(p.entry) ||
    !unique(p.locales, ["en-US", "zh-CN", "zh-TW"]) ||
    p.locales.length !== 3 ||
    !Array.isArray(p.routes) ||
    p.routes.length === 0 ||
    p.routes.length > 32
  )
    return false;
  const ids = new Set(),
    paths = new Set();
  for (const route of p.routes) {
    if (
      !record(route, ["id", "path", "layout"]) ||
      !match(route.id, slug) ||
      typeof route.path !== "string" ||
      !(
        route.path === "/" ||
        (route.path.startsWith("/") && safePath(route.path.slice(1)))
      ) ||
      ids.has(route.id) ||
      paths.has(route.path) ||
      typeof route.layout !== "string" ||
      !["document", "viewport"].includes(route.layout)
    )
      return false;
    ids.add(route.id);
    paths.add(route.path);
  }
  const f = value.frontend,
    d = value.data;
  if (
    !paths.has("/") ||
    !record(f, ["artifact", "sha256"]) ||
    !safePath(f.artifact) ||
    !match(f.sha256, digest) ||
    !validCapabilities(value.capabilities, value.backend != null) ||
    (value.backend != null && !validBackend(value.backend))
  )
    return false;
  if (
    !record(d, ["schema", "readable_schemas", "writes_on_startup"]) ||
    !integer(d.schema, 1, 1_000_000) ||
    !(d.writes_on_startup == null || d.writes_on_startup === false) ||
    !Array.isArray(d.readable_schemas) ||
    d.readable_schemas.length === 0 ||
    d.readable_schemas.length > 32 ||
    new Set(d.readable_schemas).size !== d.readable_schemas.length ||
    !d.readable_schemas.every((v) => integer(v, 1, 1_000_000)) ||
    !d.readable_schemas.includes(d.schema)
  )
    return false;
  return true;
}

// Inspect object keys before JSON.parse, which would discard duplicate fields.
// The bounded grammar scan also preserves Go's integer-only numeric contract.
function inspectJSON(text: string): void {
  let at = 0;
  const skip = () => {
    while (/[\x20\t\r\n]/.test(text[at] ?? "\0")) at++;
  };
  const fail = (): never => {
    throw new DescriptorError();
  };
  function string(): string {
    if (text[at++] !== '"') return fail();
    const start = at - 1;
    while (at < text.length) {
      const char = text[at++];
      if (char === "\\") at++;
      else if (char === '"') return JSON.parse(text.slice(start, at)) as string;
    }
    return fail();
  }
  function value(depth: number): void {
    if (depth > 24) fail();
    skip();
    const first = text[at];
    if (first === "{") {
      at++;
      skip();
      const seen = new Set<string>();
      if (text[at] === "}") {
        at++;
        return;
      }
      while (true) {
        skip();
        const key = string();
        if (!match(key, /^[a-z][a-z0-9_]*$/) || seen.has(key)) fail();
        seen.add(key);
        skip();
        if (text[at++] !== ":") fail();
        value(depth + 1);
        skip();
        const separator = text[at++];
        if (separator === "}") return;
        if (separator !== ",") fail();
      }
    }
    if (first === "[") {
      at++;
      skip();
      if (text[at] === "]") {
        at++;
        return;
      }
      while (true) {
        value(depth + 1);
        skip();
        const separator = text[at++];
        if (separator === "]") return;
        if (separator !== ",") fail();
      }
    }
    if (first === '"') {
      string();
      return;
    }
    const start = at;
    while (at < text.length && !/[\x20\t\r\n,}\]]/.test(text[at])) at++;
    const primitive = text.slice(start, at);
    if (
      !["true", "false", "null"].includes(primitive) &&
      !match(primitive, /^-?(0|[1-9][0-9]*)$/)
    )
      fail();
  }
  skip();
  if (text[at] !== "{") fail();
  value(1);
  skip();
  if (at !== text.length) fail();
}

export function parseDescriptor(raw: Uint8Array): Descriptor {
  try {
    if (raw.byteLength === 0 || raw.byteLength > MAX_DESCRIPTOR_BYTES)
      throw new DescriptorError();
    // Preserve a BOM so JSON parsing rejects it just as the host parser does.
    const text = new TextDecoder("utf-8", {
      fatal: true,
      ignoreBOM: true,
    }).decode(raw);
    inspectJSON(text);
    const value: unknown = JSON.parse(text);
    if (!validManifest(value)) throw new DescriptorError();
    return value;
  } catch {
    throw new DescriptorError();
  }
}
