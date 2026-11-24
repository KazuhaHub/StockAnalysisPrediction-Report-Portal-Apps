import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { mount } from "./harness";
import { backend } from "./fixtures";
import enUS from "../locales/en-US.json";

vi.mock("../src/components/EChart", () => ({
  EChart: ({ label }: { label: string }) => <div aria-label={label} />,
}));

// The stylesheet is read from disk: a CSS import is empty under vitest.
const css = readFileSync(
  join(import.meta.dirname, "../src/style.css"),
  "utf8",
).replace(/\/\*[\s\S]*?\*\//g, "");
const coarse = [
  ...css.matchAll(/@media \(pointer: coarse\)\s*\{([\s\S]*?)\n\}/g),
]
  .map((m) => m[1])
  .join("\n");

test("the module switcher is a row of six tabs, the current one selected", async () => {
  await mount(backend(), { path: "/etf" });
  const tabs = await screen.findAllByRole("tab");
  expect(tabs.map((tab) => tab.textContent)).toEqual([
    enUS.nav_overview,
    enUS.nav_margin,
    enUS.nav_sentiment,
    enUS.nav_etf,
    enUS.nav_panorama,
    enUS.nav_quant,
  ]);
  expect(
    tabs.filter((t) => t.getAttribute("aria-selected") === "true"),
  ).toEqual([screen.getByRole("tab", { name: enUS.nav_etf })]);
  expect(
    within(
      screen.getByRole("navigation", { name: enUS.navigation }),
    ).getAllByRole("tab"),
  ).toHaveLength(6);
});

test("choosing a tab navigates to its module", async () => {
  const app = await mount(backend(), { path: "/etf" });
  fireEvent.click(await screen.findByRole("tab", { name: enUS.nav_quant }));
  await waitFor(() =>
    expect(
      screen
        .getByRole("tab", { name: enUS.nav_quant })
        .getAttribute("aria-selected"),
    ).toBe("true"),
  );
  // The host hears about the new page after the tab has switched.
  await waitFor(() => expect(app.page()?.page.title).toBe(enUS.quantTitle));
});

// Tabs that do not fit their row scroll, with a fade at the side that has
// more, and never show antd's "…" menu, which hides tabs behind a click.
test("a tab row that overflows never shows antd's overflow menu", () => {
  expect(css).toMatch(/\.ant-tabs-nav-operations\s*\{[^}]*display:\s*none/);
});

test("a tab row fades the side that has more tabs", () => {
  expect(css).toMatch(/\.ant-tabs-nav-wrap-ping-left[^{]*\{[^}]*mask-image/);
  expect(css).toMatch(/\.ant-tabs-nav-wrap-ping-right[^{]*\{[^}]*mask-image/);
});

test("tabs are at least 44px high on touch screens", () => {
  expect(coarse).toMatch(/\.mm-nav-tab\s*\{[^}]*min-height:\s*44px/);
});

test("the tabs are a swipeable row with edge fades, not an antd tab bar", async () => {
  await mount(backend(), { path: "/" });
  const list = await screen.findByRole("tablist");
  expect(list.classList.contains("mm-scroll-row")).toBe(true);
  expect(document.querySelector(".ant-tabs-nav-operations")).toBeNull();
  expect(css).toMatch(/\.mm-scroll-row\[data-end\]\s*\{[^}]*mask-image/);
  expect(css).toMatch(/\.mm-scroll-row\[data-start\]\s*\{[^}]*mask-image/);
});

test("arrow keys move between tabs", async () => {
  await mount(backend(), { path: "/etf" });
  const etf = await screen.findByRole("tab", { name: enUS.nav_etf });
  etf.focus();
  fireEvent.keyDown(etf, { key: "ArrowRight" });
  await waitFor(() =>
    expect(
      screen
        .getByRole("tab", { name: enUS.nav_panorama })
        .getAttribute("aria-selected"),
    ).toBe("true"),
  );
  fireEvent.keyDown(screen.getByRole("tab", { name: enUS.nav_panorama }), {
    key: "End",
  });
  await waitFor(() =>
    expect(
      screen
        .getByRole("tab", { name: enUS.nav_quant })
        .getAttribute("aria-selected"),
    ).toBe("true"),
  );
});

// A row that is too narrow scrolls the active tab into view when it is opened.
test("scrolls the active tab into view", async () => {
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(100);
  vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockReturnValue(600);
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(100);
  vi.spyOn(HTMLElement.prototype, "offsetLeft", "get").mockImplementation(
    function (this: HTMLElement) {
      const tabs = [...(this.parentElement?.children ?? [])];
      return tabs.indexOf(this) * 100;
    },
  );
  const scrollTo = vi.fn();
  HTMLElement.prototype.scrollTo = scrollTo as never;
  await mount(backend(), { path: "/quant" });
  await screen.findByRole("tab", { name: enUS.nav_quant });
  await waitFor(() => expect(scrollTo).toHaveBeenCalled());
  expect(scrollTo.mock.calls.at(-1)![0].left).toBeGreaterThanOrEqual(400);
  vi.restoreAllMocks();
});
