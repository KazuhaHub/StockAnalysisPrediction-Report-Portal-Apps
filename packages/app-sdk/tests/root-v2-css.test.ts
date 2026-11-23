import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "vitest";

const css = readFileSync(join(__dirname, "../src/root-v2.css"), "utf8");

// Same rule as the Portal shell: when a card's title and its extra do not fit on one line, the extra
// moves to its own line instead of squeezing the title to a word per line.
test("card headers wrap their extra below the title instead of squeezing it", () => {
  expect(css).toMatch(
    /\.ant-card \.ant-card-head > \.ant-card-head-wrapper\s*\{[^}]*flex-wrap:\s*wrap/,
  );
  expect(css).toMatch(
    /\.ant-card-head \.ant-card-head-title\s*\{[^}]*flex:\s*1 0 auto[^}]*max-width:\s*100%/,
  );
  expect(css).toMatch(
    /\.ant-card-head \.ant-card-extra\s*\{[^}]*margin-inline-start:\s*auto[^}]*max-width:\s*100%/,
  );
});
