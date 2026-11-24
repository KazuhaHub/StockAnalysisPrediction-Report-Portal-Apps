import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// On a touch screen the controls get a target a finger can hit (44px) without
// changing how they look on a desktop. The stylesheet is read from disk: a CSS
// import is empty under vitest.
const css = readFileSync(
  join(import.meta.dirname, "../src/style.css"),
  "utf8",
).replace(/\/\*[\s\S]*?\*\//g, "");
const coarse = [
  ...css.matchAll(/@media \(pointer: coarse\)\s*\{([\s\S]*?)\n\}/g),
]
  .map((m) => m[1])
  .join("\n");

describe("touch targets", () => {
  it("has a touch-screen block", () => {
    expect(coarse.length).toBeGreaterThan(200);
  });

  it.each([
    ["module tabs", /\.mm-nav-tab\s*\{[^}]*min-height:\s*44px/],
    ["buttons", /\.ant-btn[^{]*\{[^}]*min-height:\s*44px/],
    ["selects", /\.ant-select-selector[^{]*\{[^}]*min-height:\s*44px/],
    ["segmented items", /\.ant-segmented-item[^{]*\{[^}]*min-height:\s*44px/],
    ["pagination", /\.ant-pagination-item[^{]*\{[^}]*height:\s*44px/],
    ["drawer close", /\.ant-drawer-close[^{]*\{[^}]*min-height:\s*44px/],
  ])("widens %s to 44px", (_name, rule) => {
    expect(coarse).toMatch(rule);
  });

  it("keeps the desktop look: the widening is under the touch query only", () => {
    expect(css.replace(coarse, "")).not.toMatch(/min-height:\s*44px/);
  });
});
