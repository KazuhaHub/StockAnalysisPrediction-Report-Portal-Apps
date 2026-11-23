import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { mount } from "./harness";
import { backend, summaries, marginRows } from "./fixtures";
import enUS from "../locales/en-US.json";
import zhCN from "../locales/zh-CN.json";
import zhTW from "../locales/zh-TW.json";
import {
  MECHANISMS,
  fragTone,
  parseRatioHist,
  ratioHistBars,
} from "../src/lib/margin";
import { heatOrder } from "../src/pages/Panorama";
import { parseRowQuery, queryRows } from "../dev/mock-backend.mjs";

// Canvas is unavailable in jsdom: charts become a stub that exposes the option
// they were given (functions are dropped by the JSON encoding).
vi.mock("../src/components/EChart", () => ({
  EChart: ({ label, option }: { label: string; option: object }) => (
    <div
      data-testid="chart"
      aria-label={label}
      data-option={JSON.stringify(option)}
    />
  ),
}));

const chartOption = (label: string) =>
  JSON.parse(
    screen.getByLabelText(label).getAttribute("data-option")!,
  ) as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const lastRows = (calls: string[]) =>
  calls.filter((c) => c.includes("/rows?") && !c.includes("size=200")).at(-1)!;
const param = (path: string, key: string) =>
  new URL(path, "http://x.invalid").searchParams.get(key);

const marginSummary = summaries.margin as { overview: object };
const hist = {
  width: 0.5,
  counts: Array.from({ length: 30 }, (_, i) => (i === 3 ? 7 : i % 4)),
  median: 4.2,
};
const withHist = (ratio_hist: unknown) => ({
  margin: {
    ...marginSummary,
    overview: { ...marginSummary.overview, ratio_hist },
  },
});

test("ratio_hist is validated: 30-ish finite non-negative counts, positive width", () => {
  expect(parseRatioHist(hist)).toEqual(hist);
  expect(parseRatioHist(undefined)).toBeNull();
  expect(parseRatioHist({ ...hist, width: 0 })).toBeNull();
  expect(parseRatioHist({ ...hist, counts: [] })).toBeNull();
  expect(parseRatioHist({ ...hist, counts: [1, "x"] })).toBeNull();
  expect(parseRatioHist({ ...hist, counts: [1, -1] })).toBeNull();
  expect(parseRatioHist({ width: 0.5, counts: [1, 2] })).toEqual({
    width: 0.5,
    counts: [1, 2],
    median: null,
  });
});

test("histogram bars: bins from 8% up are danger, the last bin is labelled open-ended", () => {
  const bars = ratioHistBars(parseRatioHist(hist)!);
  expect(bars).toHaveLength(30);
  expect(bars[0]).toMatchObject({ label: "0.0", start: 0, danger: false });
  expect(bars[15]).toMatchObject({ label: "7.5", danger: false });
  expect(bars[16]).toMatchObject({ label: "8.0", danger: true });
  expect(bars[3].value).toBe(7);
  expect(bars[29].label).toBe("≥14.5");
  expect(bars[28].label).toBe("14.0");
});

test("margin shows the crowding histogram with a median mark when the snapshot carries ratio_hist", async () => {
  await mount(backend({ summary: withHist(hist) }), { path: "/margin" });
  await screen.findByText("Stock0");
  expect(screen.queryByLabelText(enUS.margin_quantiles)).toBeNull();
  const option = chartOption(enUS.margin_hist);
  expect(option.series[0].data).toHaveLength(30);
  expect(option.xAxis.data[16]).toBe("8.0");
  // The median 4.2 falls in the bin starting at 4.0.
  expect(option.series[0].markLine.data[0].xAxis).toBe("4.0");
  expect(screen.getByText(enUS.margin_histNote)).toBeTruthy();
});

test("margin falls back to the P50/P90/P99 chart for a snapshot without ratio_hist", async () => {
  await mount(backend(), { path: "/margin" });
  await screen.findByText("Stock0");
  expect(screen.queryByLabelText(enUS.margin_hist)).toBeNull();
  expect(chartOption(enUS.margin_quantiles).xAxis.data).toEqual([
    "P50",
    "P90",
    "P99",
  ]);
});

test("the mechanism filter offers the closed set, sends mechanism=<name> and clears", async () => {
  expect(MECHANISMS).toEqual(["res2", "pledge", "unlock", "cb", "block"]);
  const app = await mount(backend(), { path: "/margin" });
  await screen.findByText("Stock0");
  expect(param(lastRows(app.calls), "mechanism")).toBeNull();
  const select = Array.from(document.querySelectorAll(".ant-select")).find(
    (el) => el.textContent === enUS.margin_mechanism,
  ) as HTMLElement;
  fireEvent.mouseDown(within(select).getByRole("combobox"));
  fireEvent.click(
    await waitFor(
      () =>
        document.querySelector(
          `.ant-select-item-option[title="${enUS.mech_pledge}"]`,
        ) as HTMLElement,
    ),
  );
  await waitFor(() =>
    expect(param(lastRows(app.calls), "mechanism")).toBe("pledge"),
  );
  expect(param(lastRows(app.calls), "page")).toBe("1");
  fireEvent.mouseEnter(select);
  fireEvent.mouseDown(select.querySelector(".ant-select-clear")!);
  fireEvent.click(select.querySelector(".ant-select-clear")!);
  await waitFor(() =>
    expect(param(lastRows(app.calls), "mechanism")).toBeNull(),
  );
});

test("mechanism copy exists in every locale", () => {
  for (const copy of [enUS, zhCN, zhTW])
    for (const name of MECHANISMS)
      expect((copy as Record<string, string>)[`mech_${name}`]).toBeTruthy();
});

test("fragility tone: above 90 is danger, above 70 warning, else default", () => {
  expect(fragTone(90.01)).toBe("danger");
  expect(fragTone(90)).toBe("warning");
  expect(fragTone(70.01)).toBe("warning");
  expect(fragTone(70)).toBeUndefined();
  expect(fragTone(0)).toBeUndefined();
  expect(fragTone(null)).toBeUndefined();
});

test("the fragility column is a progress bar coloured by tone", async () => {
  const rows = [95, 80, 50, 100].map((frag, i) => ({
    ...marginRows[i],
    code: `60000${i}`,
    name: `Frag${frag}`,
    frag,
  }));
  await mount(backend({ rows: { margin: rows } }), { path: "/margin" });
  await screen.findByText("Frag95");
  const bar = (name: string) =>
    screen
      .getByText(name)
      .closest("tr")!
      .querySelector('[role="progressbar"]') as HTMLElement;
  expect(bar("Frag95").getAttribute("aria-valuenow")).toBe("95");
  expect(bar("Frag50").getAttribute("aria-valuenow")).toBe("50");
  const color = (name: string) =>
    (
      bar(name).querySelector(".ant-progress-track") as HTMLElement
    ).style.getPropertyValue("--progress-line-stroke-color");
  expect(color("Frag95")).toBe("#ff4d4f");
  expect(color("Frag80")).toBe("#faad14");
  expect(["#ff4d4f", "#faad14"]).not.toContain(color("Frag50"));
  // A full bar is the worst value, not a success: it keeps its number and gets no success styling.
  // A score out of 100, not a percentage.
  expect(bar("Frag100").textContent).toBe("100");
  expect(bar("Frag95").textContent).toBe("95");
  expect(bar("Frag95").getAttribute("aria-label")).toBe(enUS.col_frag);
  expect(bar("Frag100").className).not.toContain("ant-progress-status-success");
});

test("heatmap leaves out industries without a name", () => {
  const names = heatOrder([
    { name: "", n: 9, mktcap: 900 },
    { name: "kept", n: 1, mktcap: 1 },
    { n: 5, mktcap: 500 },
  ] as never).map((i) => i.name);
  expect(names).toEqual(["kept"]);
});

test("heatmap industries are ordered by market cap, then stock count; without mktcap by count", () => {
  const names = (list: object[]) => heatOrder(list as never).map((i) => i.name);
  expect(
    names([
      { name: "small", n: 900, mktcap: 10, s_value: 1 },
      { name: "big", n: 10, mktcap: 500, s_value: 1 },
      { name: "none", n: 5000, s_value: 1 },
      { name: "mid", n: 1, mktcap: 100, s_value: 1 },
    ]),
  ).toEqual(["big", "mid", "small", "none"]);
  expect(
    names([
      { name: "a", n: 1 },
      { name: "b", n: 3 },
      { name: "c", n: 2 },
    ]),
  ).toEqual(["b", "c", "a"]);
});

test("panorama heatmap lists industries by market cap, including one with no score as an empty row", async () => {
  const base = summaries.panorama as object;
  const industries = [
    { name: "Small", n: 900, mktcap: 100, s_value: 48, s_growth: 51 },
    { name: "Giant", n: 10, mktcap: 9000, s_value: 60, s_growth: 40 },
    { name: "Unscored", n: 5, mktcap: 500 },
  ];
  await mount(backend({ summary: { panorama: { ...base, industries } } }), {
    path: "/panorama",
  });
  await screen.findByText("Pano0");
  const option = chartOption(enUS.pano_heat);
  expect(option.yAxis.data).toEqual(["Giant", "Unscored", "Small"]);
  // Only scored cells carry a value; the unscored row stays blank.
  expect(option.series[0].data.every((p: number[]) => p[1] !== 1)).toBe(true);
  expect(option.series[0].data).toHaveLength(4);
});

test("the dev mock mirrors the service: mechanism predicates, closed names, margin only", () => {
  const rows = [
    { code: "000001", res_cnt: 2 },
    { code: "000002", pld_room: 14.9 },
    { code: "000003", pld_room: 15, ulk60: 0, cb_prem: 0, blk_disc: -3 },
    { code: "000004", ulk60: 1 },
    { code: "000005", cb_prem: -1 },
    { code: "000006", blk_disc: -3.5 },
  ];
  const codes = (qs: string) =>
    queryRows(rows, parseRowQuery(new URLSearchParams(qs))!).items.map((r) =>
      r.code.slice(5),
    );
  expect(codes("mechanism=res2")).toEqual(["1"]);
  expect(codes("mechanism=pledge")).toEqual(["2"]);
  expect(codes("mechanism=unlock")).toEqual(["4"]);
  expect(codes("mechanism=cb")).toEqual(["5"]);
  expect(codes("mechanism=block")).toEqual(["6"]);
  expect(codes("mechanism=cb%7Cblock")).toEqual(["5", "6"]);
  for (const bad of ["nope", "", "cb%7C", "cb%7Ccb", "res_cnt%3E%3D2"])
    expect(parseRowQuery(new URLSearchParams(`mechanism=${bad}`))).toBeNull();
  expect(parseRowQuery(new URLSearchParams("mechanism=cb"), "etf")).toBeNull();
});
