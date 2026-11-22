import { Buffer } from "node:buffer";
import { crc32 } from "node:zlib";
import { TextDecoder, TextEncoder } from "node:util";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import corpus from "./fixtures/descriptor-v2.json";
import { parseDescriptor } from "../src/descriptor-v2";

beforeEach(() => {
  vi.stubGlobal("TextDecoder", TextDecoder);
  vi.stubGlobal("TextEncoder", TextEncoder);
});
afterEach(() => vi.unstubAllGlobals());

const SIGNATURE = Buffer.from("89504e470d0a1a0a", "hex");

function chunk(type: string, data: Buffer): Buffer {
  const head = Buffer.alloc(8);
  head.writeUInt32BE(data.length, 0);
  head.write(type, 4, "latin1");
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([head.subarray(4), data])), 0);
  return Buffer.concat([head, data, crc]);
}

// A structurally valid PNG prefix; the pixel data is irrelevant to the TS check.
function png(width: number, height: number, padTo = 0): Buffer {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;
  ihdr[9] = 6;
  const raw = Buffer.concat([
    SIGNATURE,
    chunk("IHDR", ihdr),
    chunk("IEND", Buffer.alloc(0)),
  ]);
  return padTo > raw.length
    ? Buffer.concat([raw, Buffer.alloc(padTo - raw.length)])
    : raw;
}

function descriptor(mutate: (d: any) => void): Uint8Array {
  const base = JSON.parse(
    Buffer.from(
      corpus.cases.find((c) => c.valid)!.input_base64,
      "base64",
    ).toString("utf8"),
  );
  base.presentation.display = {
    icon: "file-text",
    texts: [
      { locale: "en-US", name: "Notes", description: "Personal notes" },
      { locale: "zh-CN", name: "笔记", description: "个人笔记" },
      { locale: "zh-TW", name: "筆記", description: "個人筆記" },
    ],
  };
  mutate(base);
  return new TextEncoder().encode(JSON.stringify(base));
}

const withName = (name: unknown) =>
  descriptor((d) => (d.publisher_name = name));
const withIcon = (icon: unknown) =>
  descriptor((d) => (d.presentation.display.icon_png = icon));
const b64 = (raw: Buffer) => raw.toString("base64");

test("publisher_name accepts plain display text and absence", () => {
  expect(parseDescriptor(withName("Kazuha Hub")).publisher_name).toBe(
    "Kazuha Hub",
  );
  expect(
    parseDescriptor(withName("笔".repeat(64))).publisher_name,
  ).toHaveLength(64);
  expect(parseDescriptor(descriptor(() => {})).publisher_name).toBeUndefined();
});

test("publisher_name refuses non-NFC, format, control, oversize and badly spaced text", () => {
  for (const bad of [
    "Café",
    "a‍b",
    "a‮b",
    "a\u0007b",
    "a".repeat(65),
    "",
    " Kazuha",
    "Kazuha ",
    "Kazuha  Hub",
    "a\ud800b",
    "a�b",
    7,
  ]) {
    expect(() => parseDescriptor(withName(bad)), JSON.stringify(bad)).toThrow();
  }
});

test("icon_png accepts a square 64-256 px PNG within the size cap", () => {
  for (const size of [64, 128, 256]) {
    expect(
      parseDescriptor(withIcon(b64(png(size, size)))).presentation.display
        ?.icon_png,
    ).toBeDefined();
  }
  expect(() =>
    parseDescriptor(withIcon(b64(png(64, 64, 16 * 1024)))),
  ).not.toThrow();
});

test("icon_png refuses wrong formats, dimensions, sizes and non-strict base64", () => {
  const good = b64(png(64, 64));
  const cases: [string, unknown][] = [
    ["gif", b64(Buffer.from("GIF89a\x01\x00\x01\x00\x00\x00\x00;", "latin1"))],
    ["svg", b64(Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"/>'))],
    ["300x300", b64(png(300, 300))],
    ["63x63", b64(png(63, 63))],
    ["64x65", b64(png(64, 65))],
    ["zero", b64(png(0, 0))],
    ["over cap", b64(png(64, 64, 16 * 1024 + 1))],
    [
      "bad ihdr crc",
      b64(
        Buffer.concat([
          png(64, 64).subarray(0, 29),
          Buffer.from([0, 0, 0, 0]),
          png(64, 64).subarray(33),
        ]),
      ),
    ],
    ["truncated", b64(png(64, 64).subarray(0, 20))],
    ["empty", ""],
    ["not a string", 12],
    ["newline", good.slice(0, 8) + "\n" + good.slice(8)],
    ["unpadded", b64(png(64, 64, 58)).replace(/=+$/, "")],
    ["url-safe alphabet", good.replace(/\+/g, "-").replace(/\//g, "_") + "-_"],
    ["trailing space", good + " "],
    ["data uri", "data:image/png;base64," + good],
    ["nonzero pad bits", noncanonicalPad()],
  ];
  for (const [name, icon] of cases) {
    expect(() => parseDescriptor(withIcon(icon)), name).toThrow();
  }
});

// Standard base64 whose final group sets bits that decode drops (Go's Strict() refuses it).
function noncanonicalPad(): string {
  for (let pad = 1; pad <= 2; pad++) {
    const raw = png(64, 64);
    if (raw.length % 3 === 3 - pad) {
      const text = b64(raw);
      const at = text.length - pad - 1;
      const alphabet =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
      const flipped = alphabet[(alphabet.indexOf(text[at]) + 1) % 64];
      return text.slice(0, at) + flipped + text.slice(at + 1);
    }
  }
  // Fall back to a padded encoding whose pad bits we can dirty by appending a byte.
  const raw = Buffer.concat([png(64, 64), Buffer.from([0])]);
  const text = b64(raw);
  const pad = text.endsWith("==") ? 2 : text.endsWith("=") ? 1 : 0;
  const at = text.length - pad - 1;
  const alphabet =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  return (
    text.slice(0, at) +
    alphabet[(alphabet.indexOf(text[at]) + 1) % 64] +
    text.slice(at + 1)
  );
}
