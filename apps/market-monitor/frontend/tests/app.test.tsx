import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { mount, noData, type Handler } from "./harness";
import { backend } from "./fixtures";
import realRows from "./real-rows.json";
import { stripTags, heatRange } from "../src/pages/Sentiment";
import { formatYi, utf8Length } from "../src/lib/format";
import { valueLabel } from "../src/lib/labels";
import { locales } from "../src/lib/copy";
import enUS from "../locales/en-US.json";
import zhCN from "../locales/zh-CN.json";
import zhTW from "../locales/zh-TW.json";
import { queryRows, parseRowQuery } from "../dev/mock-backend.mjs";

// Canvas is unavailable in jsdom: charts are replaced by a stub that exposes
// the option they were given.
vi.mock("../src/components/EChart", () => ({
  EChart: ({
    label,
    option,
  }: {
    label: string;
    option: { series?: { data?: unknown[] }[] };
  }) => (
    <div
      data-testid="chart"
      aria-label={label}
      data-series={String(option.series?.length ?? 0)}
      data-points={String(option.series?.[0]?.data?.length ?? 0)}
    />
  ),
}));

/** Table page requests (the ETF category loader reads size-200 pages). */
const tableRows = (calls: string[]) =>
  calls.filter((c) => c.includes("/rows?") && !c.includes("size=200"));
const lastRows = (calls: string[]) => tableRows(calls).at(-1)!;
const param = (path: string, key: string) =>
  new URL(path, "http://x.invalid").searchParams.get(key);

test("overview shows market-level readings, run status and navigates to a dashboard", async () => {
  const app = await mount(backend());
  expect(
    await screen.findByText("Systemic-risk readings · 2026-11-16"),
  ).toBeTruthy();
  expect(screen.getByText("4.10%")).toBeTruthy();
  expect(screen.getByText("85 stocks")).toBeTruthy();
  expect(
    await screen.findByText("Succeeded", {
      selector: ".ant-table-tbody .ant-tag",
    }),
  ).toBeTruthy();
  expect(app.page().page.title).toBe("Market Monitor");
  fireEvent.click(screen.getByRole("button", { name: "Margin" }));
  await waitFor(() => expect(app.page().page.title).toBe("Margin financing"));
  expect(
    await screen.findByText(
      "Crowding quantiles (margin debt / free-float cap)",
    ),
  ).toBeTruthy();
});

test("margin pages, sorts, searches and filters on the server and opens a row detail", async () => {
  const app = await mount(backend(), { path: "/margin" });
  expect(await screen.findByText("Stock0")).toBeTruthy();
  let path = lastRows(app.calls);
  expect(param(path, "page")).toBe("1");
  expect(param(path, "size")).toBe("20");
  expect(param(path, "sort")).toBe("frag");
  expect(param(path, "order")).toBe("desc");
  expect(param(path, "date")).toBe("2026-11-16");

  fireEvent.click(await screen.findByTitle("2"));
  await screen.findByText("Stock20");
  expect(param(lastRows(app.calls), "page")).toBe("2");

  fireEvent.click(screen.getAllByText("Crowding %")[0]);
  await waitFor(() => expect(param(lastRows(app.calls), "sort")).toBe("ratio"));
  path = lastRows(app.calls);
  expect(param(path, "page")).toBe("1");

  const search = screen.getByPlaceholderText("Code or name");
  fireEvent.change(search, { target: { value: "6000" } });
  fireEvent.keyDown(search, { key: "Enter", keyCode: 13, code: "Enter" });
  await waitFor(() => expect(param(lastRows(app.calls), "q")).toBe("6000"));

  const combos = screen.getAllByRole("combobox");
  fireEvent.mouseDown(combos[1]);
  fireEvent.click(
    await waitFor(
      () =>
        document.querySelector(
          '.ant-select-item-option[title="Critical"]',
        ) as HTMLElement,
    ),
  );
  await waitFor(() =>
    expect(param(lastRows(app.calls), "f.state")).toBe("临界"),
  );
  // The whole data set is never requested: every page is bounded.
  expect(
    app.calls
      .filter((c) => c.includes("/rows?"))
      .every((c) => Number(param(c, "size")) <= 200),
  ).toBe(true);

  fireEvent.click(await screen.findByText("Stock0"));
  await waitFor(() =>
    expect(app.calls.some((c) => c.startsWith("/v1/margin/rows/600000"))).toBe(
      true,
    ),
  );
  const drawer = await waitFor(
    () => document.querySelector(".ant-drawer") as HTMLElement,
  );
  await waitFor(() =>
    expect(
      within(drawer).getAllByTestId("chart")[0].getAttribute("data-points"),
    ).toBe("60"),
  );
});

test("switching the date reloads the summary and rows for that date", async () => {
  const app = await mount(backend(), { path: "/margin" });
  await screen.findByText("Stock0");
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "Date" }));
  fireEvent.click(
    await waitFor(
      () =>
        document.querySelector(
          '.ant-select-item-option[title="2026-11-13"]',
        ) as HTMLElement,
    ),
  );
  await waitFor(() =>
    expect(app.calls).toContain("/v1/margin/summary?date=2026-11-13"),
  );
  await waitFor(() =>
    expect(param(lastRows(app.calls), "date")).toBe("2026-11-13"),
  );
});

test("a module without snapshots shows the empty state", async () => {
  await mount(backend({ dates: { margin: [] } }), { path: "/margin" });
  expect(await screen.findByText(enUS.noData)).toBeTruthy();
});

test("sentiment dashboard renders readings and alerts without markup injection", async () => {
  await mount(backend(), { path: "/sentiment" });
  expect(await screen.findByText("Current reading · 2026-11-16")).toBeTruthy();
  expect(screen.getByText("Day 23")).toBeTruthy();
  expect(screen.getByText("median +2%")).toBeTruthy();
  expect(screen.getAllByTestId("chart").length).toBeGreaterThanOrEqual(3);
});

test("etf dashboard renders flows, a paged fund table sorted by 20-day flow", async () => {
  const app = await mount(backend(), { path: "/etf" });
  expect(await screen.findByText("Latest day 2026-11-16")).toBeTruthy();
  expect(await screen.findByText("STAR50 ETF")).toBeTruthy();
  expect(param(lastRows(app.calls), "sort")).toBe("cum20");
});

test("panorama dashboard renders the summary, pages rows and opens the valuation drawer", async () => {
  const app = await mount(backend(), { path: "/panorama" });
  expect(await screen.findByText("5,588")).toBeTruthy();
  expect(await screen.findByText("Pano0")).toBeTruthy();
  expect(param(lastRows(app.calls), "sort")).toBe("s_value");
  fireEvent.click(screen.getByText("Pano0"));
  await waitFor(() =>
    expect(
      app.calls.some((c) => c.startsWith("/v1/panorama/rows/000001")),
    ).toBe(true),
  );
  const drawer = await waitFor(
    () => document.querySelector(".ant-drawer") as HTMLElement,
  );
  await waitFor(() =>
    expect(within(drawer).getAllByTestId("chart").length).toBe(2),
  );
});

test("a failing backend shows an error, and the zh-CN locale applies", async () => {
  await mount(() => ({ status: 409, body: { error: "unavailable" } }), {
    path: "/etf",
    locale: "zh-CN",
  });
  expect(await screen.findByText(zhCN.unavailable)).toBeTruthy();
});

test("all locales define exactly the same keys", () => {
  const keys = (v: object) => Object.keys(v).sort();
  expect(keys(zhCN)).toEqual(keys(enUS));
  expect(keys(zhTW)).toEqual(keys(enUS));
});

test("the dev mock backend query helpers page, sort (nulls last), filter and validate parameters", () => {
  const rows = [
    { code: "000001", name: "alpha", v: 2, tags: "x|y" },
    { code: "000002", name: "beta", v: null, tags: "y" },
    { code: "600003", name: "gamma", v: 9, tags: "" },
  ];
  const q = (s: string) => parseRowQuery(new URLSearchParams(s))!;
  expect(
    queryRows(rows, q("sort=v&order=desc")).items.map((r) => r.code),
  ).toEqual(["600003", "000001", "000002"]);
  expect(
    queryRows(rows, q("sort=v&order=asc")).items.map((r) => r.code),
  ).toEqual(["000001", "600003", "000002"]);
  expect(queryRows(rows, q("f.tags=y")).total).toBe(2);
  expect(queryRows(rows, q("q=0000")).total).toBe(2);
  expect(queryRows(rows, q("q=amm")).total).toBe(1);
  expect(queryRows(rows, q("page=2&size=2")).items.map((r) => r.code)).toEqual([
    "600003",
  ]);
  expect(parseRowQuery(new URLSearchParams("size=201"))).toBeNull();
  expect(parseRowQuery(new URLSearchParams("sort=Bad"))).toBeNull();
  expect(parseRowQuery(new URLSearchParams("what=1"))).toBeNull();
});

const callsOf = (calls: string[], needle: string) =>
  calls.filter((c) => c.includes(needle));

function pickOption(title: string) {
  return waitFor(() => {
    const el = document.querySelector(
      `.ant-select-item-option[title="${title}"]`,
    ) as HTMLElement | null;
    if (!el) throw new Error(`no option ${title}`);
    return el;
  });
}

test("a stale summary arriving after a date change does not overwrite the newer date", async () => {
  const release: Array<() => void> = [];
  const base = backend({
    dates: { margin: ["2026-11-16", "2026-11-13", "2026-11-12"] },
  });
  // The summary of 2026-11-13 is held back until the test releases it.
  const handler: Handler = (path, params) => {
    const reply = base(path, params);
    if (path === "/v1/margin/summary" && params.get("date") === "2026-11-13")
      return new Promise((resolve) => {
        release.push(() => {
          resolve(reply as never);
        });
      });
    return reply;
  };
  await mount(handler, { path: "/margin" });
  await screen.findByText("Stock scan · 2026-11-16");
  const date = screen.getByRole("combobox", { name: "Date" });
  fireEvent.mouseDown(date);
  fireEvent.click(await pickOption("2026-11-13"));
  fireEvent.mouseDown(date);
  fireEvent.click(await pickOption("2026-11-12"));
  await screen.findByText("Stock scan · 2026-11-12");
  release.forEach((fn) => {
    fn();
  });
  await new Promise((resolve) => setTimeout(resolve, 50));
  expect(screen.queryByText("Stock scan · 2026-11-13")).toBeNull();
  expect(screen.getByText("Stock scan · 2026-11-12")).toBeTruthy();
});

test("Refresh keeps the page mounted with its search, filters, view and sends one dates then one summary request", async () => {
  const app = await mount(backend(), { path: "/margin" });
  await screen.findByText("Stock0");
  const search = screen.getByPlaceholderText("Code or name");
  fireEvent.change(search, { target: { value: "6000" } });
  fireEvent.keyDown(search, { key: "Enter", keyCode: 13, code: "Enter" });
  await waitFor(() => expect(param(lastRows(app.calls), "q")).toBe("6000"));
  fireEvent.mouseDown(screen.getAllByRole("combobox")[1]);
  fireEvent.click(await pickOption("Critical"));
  fireEvent.click(screen.getByText("Holder-structure view"));
  await waitFor(() =>
    expect(screen.getAllByText("Pledge %").length).toBeGreaterThan(0),
  );
  await waitFor(() =>
    expect(param(lastRows(app.calls), "f.state")).toBe("临界"),
  );

  const before = app.calls.length;
  const searchNode = screen.getByPlaceholderText("Code or name");
  app.invoke("refresh");
  await waitFor(() =>
    expect(callsOf(app.calls.slice(before), "/summary").length).toBe(1),
  );
  await new Promise((resolve) => setTimeout(resolve, 50));
  const sent = app.calls.slice(before);
  expect(callsOf(sent, "/dates")).toHaveLength(1);
  expect(callsOf(sent, "/summary")).toHaveLength(1);
  expect(sent.findIndex((c) => c.includes("/dates"))).toBeLessThan(
    sent.findIndex((c) => c.includes("/summary")),
  );
  // Same DOM nodes and unchanged state after the refresh.
  expect(screen.getByPlaceholderText("Code or name")).toBe(searchNode);
  expect((searchNode as HTMLInputElement).value).toBe("6000");
  expect(screen.getAllByText("Pledge %").length).toBeGreaterThan(0);
  expect(param(lastRows(app.calls), "q")).toBe("6000");
  expect(param(lastRows(app.calls), "f.state")).toBe("临界");
});

test("a date change keeps the filters and resets the page", async () => {
  const app = await mount(backend(), { path: "/margin" });
  await screen.findByText("Stock0");
  fireEvent.mouseDown(screen.getAllByRole("combobox")[1]);
  fireEvent.click(await pickOption("Critical"));
  fireEvent.click(await screen.findByTitle("2"));
  await waitFor(() => expect(param(lastRows(app.calls), "page")).toBe("2"));
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "Date" }));
  fireEvent.click(await pickOption("2026-11-13"));
  await waitFor(() =>
    expect(param(lastRows(app.calls), "date")).toBe("2026-11-13"),
  );
  const path = lastRows(app.calls);
  expect(param(path, "page")).toBe("1");
  expect(param(path, "f.state")).toBe("临界");
});

test("the run history shows even when the risk snapshot has no data", async () => {
  await mount(
    (path, params) =>
      path.startsWith("/v1/risk/") ? noData : backend()(path, params),
    { path: "/" },
  );
  expect(await screen.findByText(enUS.noData)).toBeTruthy();
  expect(
    await screen.findByText("Succeeded", {
      selector: ".ant-table-tbody .ant-tag",
    }),
  ).toBeTruthy();
});

test("selectable rows are keyboard operable and non-selectable rows are inert", async () => {
  const app = await mount(backend(), { path: "/margin" });
  const row = (await screen.findByText("Stock0")).closest("tr")!;
  expect(row.getAttribute("tabindex")).toBe("0");
  row.focus();
  fireEvent.keyDown(row, { key: "Enter" });
  await waitFor(() =>
    expect(app.calls.some((c) => c.startsWith("/v1/margin/rows/600000"))).toBe(
      true,
    ),
  );
  fireEvent.keyDown(document.querySelector(".ant-drawer")!, { key: "Escape" });
  fireEvent.click(document.querySelector(".ant-drawer-close")!);
  const second = screen.getByText("Stock1").closest("tr")!;
  fireEvent.keyDown(second, { key: " " });
  await waitFor(() =>
    expect(app.calls.some((c) => c.startsWith("/v1/margin/rows/600001"))).toBe(
      true,
    ),
  );
});

test("etf rows are not focusable and carry no pointer affordance", async () => {
  await mount(backend(), { path: "/etf" });
  const row = (await screen.findByText("STAR50 ETF")).closest("tr")!;
  expect(row.hasAttribute("tabindex")).toBe(false);
  expect(row.hasAttribute("aria-haspopup")).toBe(false);
  expect(row.classList.contains("mm-row-select")).toBe(false);
});

test("etf categories also come from the rows (at most two size-200 requests)", async () => {
  const app = await mount(backend(), { path: "/etf" });
  await screen.findByText("STAR50 ETF");
  await waitFor(() =>
    expect(callsOf(app.calls, "size=200").length).toBeGreaterThan(0),
  );
  expect(callsOf(app.calls, "size=200").length).toBeLessThanOrEqual(2);
  fireEvent.mouseDown(screen.getAllByRole("combobox")[1]);
  expect(await pickOption("国证2000")).toBeTruthy();
  expect(await pickOption("沪深300")).toBeTruthy();
});

test("search input limits are bytes: a value over 64 bytes is flagged and never requested", async () => {
  const app = await mount(backend(), { path: "/margin" });
  await screen.findByText("Stock0");
  const search = screen.getByPlaceholderText("Code or name");
  const long = "股".repeat(22); // 22 characters, 66 bytes
  expect(long.length).toBeLessThan(64);
  expect(utf8Length(long)).toBe(66);
  fireEvent.change(search, { target: { value: long } });
  expect((search as HTMLInputElement).value).toBe(long);
  expect(await screen.findByText(enUS.inputTooLong)).toBeTruthy();
  fireEvent.keyDown(search, { key: "Enter", keyCode: 13, code: "Enter" });
  // rc-input locks Enter until the key is released.
  fireEvent.keyUp(search, { key: "Enter", keyCode: 13, code: "Enter" });
  await new Promise((resolve) => setTimeout(resolve, 50));
  expect(tableRows(app.calls).every((c) => !c.includes("q="))).toBe(true);

  const fits = "股".repeat(21); // 63 bytes
  fireEvent.change(search, { target: { value: fits } });
  expect(screen.queryByText(enUS.inputTooLong)).toBeNull();
  fireEvent.keyDown(search, { key: "Enter", keyCode: 13, code: "Enter" });
  await waitFor(() => expect(param(lastRows(app.calls), "q")).toBe(fits));
});

test("a sort on a column the other margin view lacks goes back to the default, and the default column never leaves sorted order", async () => {
  const app = await mount(backend(), { path: "/margin" });
  await screen.findByText("Stock0");
  fireEvent.click(screen.getAllByText("Crowding %")[0]);
  await waitFor(() => expect(param(lastRows(app.calls), "sort")).toBe("ratio"));
  fireEvent.click(screen.getByText("Holder-structure view"));
  await waitFor(() =>
    expect(screen.getAllByText("Pledge %").length).toBeGreaterThan(0),
  );
  await waitFor(() => expect(param(lastRows(app.calls), "sort")).toBe("frag"));
  expect(param(lastRows(app.calls), "order")).toBe("desc");
  fireEvent.click(screen.getByText("Leverage view"));
  await screen.findAllByText("Fragility");

  // Cycle the default-sorted column: ascending, then back to the default.
  fireEvent.click(screen.getAllByText("Fragility")[0]);
  await waitFor(() => expect(param(lastRows(app.calls), "order")).toBe("asc"));
  fireEvent.click(screen.getAllByText("Fragility")[0]);
  await waitFor(() => expect(param(lastRows(app.calls), "order")).toBe("desc"));
  expect(param(lastRows(app.calls), "sort")).toBe("frag");
  fireEvent.click(screen.getAllByText("Fragility")[0]);
  fireEvent.click(screen.getAllByText("Fragility")[0]);
  await new Promise((resolve) => setTimeout(resolve, 30));
  expect(tableRows(app.calls).every((c) => param(c, "sort") !== null)).toBe(
    true,
  );
});

test("margin and panorama render real rows with null fields, in every locale", async () => {
  const rows = { margin: realRows.margin, panorama: realRows.panorama };
  await mount(backend({ rows }), { path: "/margin", locale: "zh-TW" });
  expect(await screen.findByText("平安银行")).toBeTruthy();
  // Display labels follow the locale; the raw data value is not shown.
  expect(screen.getAllByText("安全").length).toBeGreaterThan(0);
  expect(screen.getAllByText("潛伏").length).toBeGreaterThan(0);
  expect(screen.queryByText("潜伏")).toBeNull();
  fireEvent.click(screen.getByText("平安银行"));
  const drawer = await waitFor(
    () => document.querySelector(".ant-drawer") as HTMLElement,
  );
  await waitFor(() => expect(within(drawer).getAllByText("無").length).toBe(3));
});

test("panorama real rows: a missing strategy score is listed, not drawn as zero", async () => {
  const app = await mount(backend({ rows: { panorama: realRows.panorama } }), {
    path: "/panorama",
  });
  const row = (await screen.findByText("000002", { exact: false })).closest(
    "tr",
  )!;
  expect(row).toBeTruthy();
  expect(
    within(document.body).getAllByText("Valuation label").length,
  ).toBeGreaterThan(0);
  fireEvent.click(row);
  await waitFor(() =>
    expect(
      app.calls.some((c) => c.startsWith("/v1/panorama/rows/000002")),
    ).toBe(true),
  );
  const drawer = await waitFor(
    () => document.querySelector(".ant-drawer") as HTMLElement,
  );
  expect(await within(drawer).findByText("No score: Dividend")).toBeTruthy();
  expect(within(drawer).getByText("Deeply undervalued")).toBeTruthy();
});

test("stripTags removes only bold and line-break markup", () => {
  expect(stripTags("a <b>+2%</b> b")).toBe("a +2% b");
  expect(stripTags("x<br>y<br/>z")).toBe("x y z");
  const text = "breadth <10% ... back above >35%";
  expect(stripTags(text)).toBe(text);
  expect(stripTags(undefined)).toBe("");
});

test("the heatmap range is symmetric around zero and falls back when empty", () => {
  expect(heatRange([[{ v: -2.18 }, { v: 5.51 }, { v: null }]])).toEqual({
    min: -6,
    max: 6,
  });
  expect(heatRange(undefined)).toEqual({ min: -3, max: 3 });
  expect(heatRange([[{ v: null }]])).toEqual({ min: -3, max: 3 });
});

test("amount units and categorical labels come from the locale copy", () => {
  expect(formatYi(25000, "zh-CN")).toBe("2.50 万亿");
  expect(formatYi(25000, "zh-TW")).toBe("2.50 萬億");
  expect(formatYi(25000, "en-US")).toBe("2.50 tn");
  expect(formatYi(2832, "zh-CN")).toBe("2832 亿");
  expect(formatYi(2832, "zh-TW")).toBe("2832 億");
  expect(formatYi(2832, "en-US")).toBe("283.2 bn");
  expect(valueLabel(locales["zh-CN"], "临界")).toBe("临界");
  expect(valueLabel(locales["zh-TW"], "临界")).toBe("臨界");
  expect(valueLabel(locales["en-US"], "临界")).toBe("Critical");
  expect(valueLabel(locales["en-US"], "新值")).toBe("新值");
  expect(valueLabel(locales["en-US"], "constructor")).toBe("constructor");
  expect(enUS.sent_disp).not.toMatch(/\{rank\}th/);
});
