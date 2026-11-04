import { Buffer } from "node:buffer";
import { TextDecoder, TextEncoder } from "node:util";
import { afterEach, expect, test, vi } from "vitest";
import corpus from "./fixtures/descriptor-v2.json";
import { parseDescriptor } from "../src/descriptor-v2";
afterEach(() => vi.unstubAllGlobals());
test("signed display copy requires complete locales, bounded plain text and an approved icon", () => {
  vi.stubGlobal("TextDecoder", TextDecoder);
  vi.stubGlobal("TextEncoder", TextEncoder);
  const base = JSON.parse(
    Buffer.from(
      corpus.cases.find((c) => c.valid)!.input_base64,
      "base64",
    ).toString("utf8"),
  );
  const display = {
    icon: "file-text",
    texts: [
      { locale: "en-US", name: "Notes", description: "Personal notes" },
      { locale: "zh-CN", name: "笔记", description: "个人笔记" },
      { locale: "zh-TW", name: "筆記", description: "個人筆記" },
    ],
  };
  base.presentation.display = display;
  expect(
    parseDescriptor(new TextEncoder().encode(JSON.stringify(base))).presentation
      .display,
  ).toEqual(display);
  for (const mutate of [
    (d: typeof display) => {
      d.texts.pop();
    },
    (d: typeof display) => {
      d.texts[1].locale = "en-US";
    },
    (d: typeof display) => {
      d.icon = "https://example.invalid/icon.svg";
    },
    (d: typeof display) => {
      d.texts[0].name = " Notes";
    },
    (d: typeof display) => {
      d.texts[0].name = "Notes\u202e";
    },
    (d: typeof display) => {
      d.texts[0].name = "笔".repeat(81);
    },
  ]) {
    const d = structuredClone(display);
    mutate(d);
    base.presentation.display = d;
    expect(() =>
      parseDescriptor(new TextEncoder().encode(JSON.stringify(base))),
    ).toThrow();
  }
});
