// @vitest-environment node
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import Ajv2020 from "ajv/dist/2020.js";
import { expect, test } from "vitest";
import corpus from "./fixtures/descriptor-v2.json";
import { parseDescriptor } from "../src/descriptor-v2";
import {
  DESCRIPTOR_SCHEMA_SHA256,
  DESCRIPTOR_FIELDS,
} from "../src/descriptor-contract.generated";

const bytes = readFileSync("schema/descriptor-v2.schema.json");
const schema = JSON.parse(bytes.toString("utf8"));
const ajv = new Ajv2020({ strict: true, strictSchema: false });
const validate = ajv.compile(schema);
const validCases = corpus.cases.filter((item) => item.valid);
const fixture = (managed = false): Record<string, any> => {
  const item = validCases.find(
    (item) =>
      Boolean(
        JSON.parse(Buffer.from(item.input_base64, "base64").toString("utf8"))
          .backend,
      ) === managed,
  )!;
  return JSON.parse(Buffer.from(item.input_base64, "base64").toString("utf8"));
};
const encoded = (value: unknown) =>
  new TextEncoder().encode(JSON.stringify(value));

test("the experimental schema is shipped next to the SDK", () => {
  expect(schema.$schema).toBe("https://json-schema.org/draft/2020-12/schema");
  expect(schema.$defs.Manifest.additionalProperties).toBe(false);
  expect(createHash("sha256").update(bytes).digest("hex")).toBe(
    DESCRIPTOR_SCHEMA_SHA256,
  );
  for (const [name, fields] of Object.entries(DESCRIPTOR_FIELDS)) {
    expect(Object.keys(schema.$defs[name].properties)).toEqual(fields);
  }
});

for (const item of validCases) {
  test(`schema accepts supported descriptor: ${item.name}`, () => {
    const value = JSON.parse(
      Buffer.from(item.input_base64, "base64").toString("utf8"),
    );
    expect(validate(value), JSON.stringify(validate.errors)).toBe(true);
  });
}

for (const [name, mutate] of [
  [
    "unknown field",
    (d: any) => {
      d.shell = {};
    },
  ],
  [
    "missing identity",
    (d: any) => {
      delete d.id;
    },
  ],
  [
    "unknown capability",
    (d: any) => {
      d.capabilities.required = ["host.exec"];
    },
  ],
  [
    "memory quota",
    (d: any) => {
      d.backend.resources.memory_mib = 4097;
    },
  ],
  [
    "duplicate locale",
    (d: any) => {
      d.presentation.locales[1] = d.presentation.locales[0];
    },
  ],
  [
    "wrong route type",
    (d: any) => {
      d.presentation.routes[0].layout = 1;
    },
  ],
  [
    "mutable image",
    (d: any) => {
      d.backend.image = "example.invalid/app:latest";
    },
  ],
  [
    "startup writes",
    (d: any) => {
      d.data.writes_on_startup = true;
    },
  ],
  [
    "empty range",
    (d: any) => {
      d.compatibility.platform_api = " ";
    },
  ],
] as const) {
  test(`schema and strict parser refuse ${name}`, () => {
    const value = fixture(true);
    mutate(value);
    expect(validate(value)).toBe(false);
    expect(() => parseDescriptor(encoded(value))).toThrow();
  });
}

// Standard JSON Schema validates decoded values. The byte/semantic parser is
// still mandatory even when editor validation succeeds.
for (const [name, mutate] of [
  [
    "traversal",
    (d: any) => {
      d.frontend.artifact = "../ui.zip";
    },
  ],
  [
    "background dependency",
    (d: any) => {
      d.capabilities = { required: ["tasks.schedule"], optional: [] };
    },
  ],
  [
    "current data schema absent",
    (d: any) => {
      d.data.readable_schemas = [d.data.schema + 1];
    },
  ],
  [
    "duplicate route identity",
    (d: any) => {
      d.presentation.routes.push({
        ...d.presentation.routes[0],
        path: "/other",
      });
    },
  ],
] as const) {
  test(`editor structure alone is insufficient for ${name}`, () => {
    const value = fixture(true);
    mutate(value);
    expect(validate(value), JSON.stringify(validate.errors)).toBe(true);
    expect(() => parseDescriptor(encoded(value))).toThrow();
  });
}

test("decoded integer validation does not authorize decimal byte lexemes", () => {
  const text = JSON.stringify(fixture(true)).replace(
    /"pids":\d+/,
    '"pids":64.0',
  );
  expect(validate(JSON.parse(text))).toBe(true);
  expect(() => parseDescriptor(new TextEncoder().encode(text))).toThrow();
});
