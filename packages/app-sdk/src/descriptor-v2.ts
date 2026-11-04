// Experimental declaration validation only. This does not verify signatures,
// compatibility, artifact bytes, effective permissions or runtime admission.
import { parseRouteQueryRules } from "./route-query-v2";
export const MAX_DESCRIPTOR_BYTES = DESCRIPTOR_LIMITS.MaxDescriptorBytes;

export class DescriptorError extends Error {
  constructor() {
    super("invalid application descriptor");
    this.name = "DescriptorError";
  }
}

import {
  DESCRIPTOR_LIMITS,
  DESCRIPTOR_PATTERNS,
  DESCRIPTOR_CAPABILITIES,
  DESCRIPTOR_LOCALES,
  DESCRIPTOR_PLATFORMS,
  DESCRIPTOR_LAYOUTS,
  DESCRIPTOR_DISPLAY_ICONS,
  DESCRIPTOR_FIELDS,
  DESCRIPTOR_CONSTANTS,
} from "./descriptor-contract.generated";
import type { Descriptor } from "./descriptor-contract.generated";
export type { Descriptor } from "./descriptor-contract.generated";

const slug = new RegExp(DESCRIPTOR_PATTERNS.slug);
const copyKey = new RegExp(DESCRIPTOR_PATTERNS.copyKey);
const digest = new RegExp(DESCRIPTOR_PATTERNS.digest);
const range = new RegExp(DESCRIPTOR_PATTERNS.range);
const version = new RegExp(DESCRIPTOR_PATTERNS.version);
const image = new RegExp(DESCRIPTOR_PATTERNS.image);
const pathPattern = new RegExp(DESCRIPTOR_PATTERNS.path);
const keyPattern = new RegExp(DESCRIPTOR_PATTERNS.key);
const known = new Set<string>(DESCRIPTOR_CAPABILITIES);
const layouts = new Set<string>(DESCRIPTOR_LAYOUTS);

function match(
  value: unknown,
  pattern: RegExp,
  max: number = DESCRIPTOR_LIMITS.maxBackendImageBytes,
): value is string {
  return (
    typeof value === "string" &&
    value.length <= max &&
    pattern.exec(value)?.[0] === value
  );
}
function record(
  value: unknown,
  keys: readonly string[],
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
function unique(
  values: unknown,
  allowed: readonly string[],
): values is string[] {
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
    match(value, pathPattern, DESCRIPTOR_LIMITS.maxDescriptorPathBytes) &&
    !value.startsWith("/") &&
    !value.includes("..") &&
    value.split("/").every((segment) => segment !== "" && segment !== ".")
  );
}
function validVersion(value: unknown): boolean {
  if (!match(value, version, DESCRIPTOR_LIMITS.maxDescriptorVersionBytes))
    return false;
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
    !record(value, DESCRIPTOR_FIELDS.Backend) ||
    value.kind !== DESCRIPTOR_CONSTANTS.descriptorBackendKind ||
    value.protocol !== DESCRIPTOR_CONSTANTS.descriptorBackendProtocol ||
    !match(value.image, image) ||
    value.image.includes("..") ||
    value.image.includes("//") ||
    !unique(value.platforms, DESCRIPTOR_PLATFORMS)
  )
    return false;
  const r = value.resources;
  return (
    record(r, DESCRIPTOR_FIELDS.Resources) &&
    integer(
      r.memory_mib,
      DESCRIPTOR_LIMITS.minBackendMemoryMiB,
      DESCRIPTOR_LIMITS.maxBackendMemoryMiB,
    ) &&
    integer(
      r.cpu_millis,
      DESCRIPTOR_LIMITS.minBackendCPUMillis,
      DESCRIPTOR_LIMITS.maxBackendCPUMillis,
    ) &&
    integer(
      r.pids,
      DESCRIPTOR_LIMITS.minBackendPIDs,
      DESCRIPTOR_LIMITS.maxBackendPIDs,
    )
  );
}
function validCapabilities(value: unknown, backend: boolean): boolean {
  if (value === undefined || value === null) value = {};
  if (!record(value, DESCRIPTOR_FIELDS.Capabilities)) return false;
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
function displayText(value: unknown, max: number): boolean {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    [...value].length <= max &&
    value.trim() === value &&
    !/[\p{Cc}\p{Cf}\uD800-\uDFFF\uFFFD]/u.test(value)
  );
}
function validDisplay(value: unknown): boolean {
  if (
    !record(value, DESCRIPTOR_FIELDS.AppDisplay) ||
    typeof value.icon !== "string" ||
    !(DESCRIPTOR_DISPLAY_ICONS as readonly string[]).includes(value.icon) ||
    !Array.isArray(value.texts) ||
    value.texts.length !== DESCRIPTOR_LOCALES.length
  )
    return false;
  const seen = new Set<string>();
  for (const text of value.texts) {
    if (
      !record(text, DESCRIPTOR_FIELDS.AppDisplayText) ||
      typeof text.locale !== "string" ||
      !(DESCRIPTOR_LOCALES as readonly string[]).includes(text.locale) ||
      seen.has(text.locale) ||
      !displayText(text.name, DESCRIPTOR_LIMITS.MaxAppNameCharacters) ||
      !displayText(
        text.description,
        DESCRIPTOR_LIMITS.MaxAppDescriptionCharacters,
      )
    )
      return false;
    seen.add(text.locale);
  }
  return true;
}
function validManifest(value: unknown): value is Descriptor {
  if (
    !record(value, DESCRIPTOR_FIELDS.Manifest) ||
    value.format !== DESCRIPTOR_CONSTANTS.descriptorFormat ||
    !match(value.id, slug) ||
    !match(value.publisher, slug) ||
    !validVersion(value.version)
  )
    return false;
  const c = value.compatibility;
  if (
    !record(c, DESCRIPTOR_FIELDS.Compatibility) ||
    !match(c.platform_api, range) ||
    !match(c.runner_protocol, range) ||
    !c.platform_api.trim() ||
    !c.runner_protocol.trim()
  )
    return false;
  const p = value.presentation;
  if (
    !record(p, DESCRIPTOR_FIELDS.Presentation) ||
    (p.display != null && !validDisplay(p.display)) ||
    !match(p.name_key, copyKey) ||
    !match(p.description_key, copyKey) ||
    !safePath(p.entry) ||
    !unique(p.locales, DESCRIPTOR_LOCALES) ||
    p.locales.length !== DESCRIPTOR_LOCALES.length ||
    !Array.isArray(p.routes) ||
    p.routes.length === 0 ||
    p.routes.length > DESCRIPTOR_LIMITS.maxDescriptorRoutes
  )
    return false;
  const ids = new Set(),
    paths = new Set();
  for (const route of p.routes) {
    if (
      !record(route, DESCRIPTOR_FIELDS.Route) ||
      parseRouteQueryRules(route.query) === null ||
      !match(route.id, slug) ||
      typeof route.path !== "string" ||
      !(
        route.path === "/" ||
        (route.path.startsWith("/") && safePath(route.path.slice(1)))
      ) ||
      ids.has(route.id) ||
      paths.has(route.path) ||
      typeof route.layout !== "string" ||
      !layouts.has(route.layout)
    )
      return false;
    ids.add(route.id);
    paths.add(route.path);
  }
  const f = value.frontend,
    d = value.data;
  if (
    !paths.has("/") ||
    !record(f, DESCRIPTOR_FIELDS.Artifact) ||
    !safePath(f.artifact) ||
    !match(f.sha256, digest) ||
    !validCapabilities(value.capabilities, value.backend != null) ||
    (value.backend != null && !validBackend(value.backend))
  )
    return false;
  if (
    !record(d, DESCRIPTOR_FIELDS.DataCompatibility) ||
    !integer(
      d.schema,
      DESCRIPTOR_LIMITS.minDescriptorDataSchema,
      DESCRIPTOR_LIMITS.maxDescriptorDataSchema,
    ) ||
    !(d.writes_on_startup == null || d.writes_on_startup === false) ||
    !Array.isArray(d.readable_schemas) ||
    d.readable_schemas.length === 0 ||
    d.readable_schemas.length >
      DESCRIPTOR_LIMITS.maxDescriptorReadableSchemas ||
    new Set(d.readable_schemas).size !== d.readable_schemas.length ||
    !d.readable_schemas.every((v) =>
      integer(
        v,
        DESCRIPTOR_LIMITS.minDescriptorDataSchema,
        DESCRIPTOR_LIMITS.maxDescriptorDataSchema,
      ),
    ) ||
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
    if (depth > DESCRIPTOR_LIMITS.maxDescriptorDepth) fail();
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
        if (!match(key, keyPattern) || seen.has(key)) fail();
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
