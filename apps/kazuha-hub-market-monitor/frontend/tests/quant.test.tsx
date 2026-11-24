import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { mount } from "./harness";
import { backend, summaries } from "./fixtures";
import enUS from "../locales/en-US.json";
import zhCN from "../locales/zh-CN.json";
import quant from "./quant-summary.json";
import { fill } from "../src/lib/format";
import {
  histRows,
  mainTooltip,
  rebase,
  type HistTuple,
} from "../src/lib/quant";

// Canvas is unavailable in jsdom: charts become a stub exposing their option.
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

const risk = summaries.risk as object;
const withQuant = (q: unknown) =>
  backend({ summary: { risk: { ...risk, quant: q } } });

test("the quant page renders every section from the fixture", async () => {
  await mount(backend(), { path: "/quant" });
  // State cards: the state and signal names are shown as the data has them.
  const lead = await screen.findByLabelText(enUS.q_leadTitle);
  expect(within(lead).getByText(quant.state)).toBeTruthy();
  expect(within(lead).getByText(enUS.q_tag_bad)).toBeTruthy();
  expect(
    within(screen.getByLabelText(enUS.q_microTitle)).getByText(quant.mstate),
  ).toBeTruthy();
  // The state machine marks the step of the state label (熊市确认 is step 4).
  const steps = within(screen.getByLabelText(enUS.q_fsmTitle)).getAllByRole(
    "listitem",
  );
  expect(steps).toHaveLength(8);
  expect(steps[4].getAttribute("aria-current")).toBe("step");
  // Ladder tier 1 is the current one.
  const tiers = within(screen.getByLabelText(enUS.q_sPos)).getAllByRole(
    "listitem",
  );
  expect(tiers[quant.step.stage].getAttribute("aria-current")).toBe("step");
  // Daily monitoring: three gates, freshness is up to date.
  expect(screen.getByText(enUS.q_g1Ok)).toBeTruthy();
  expect(screen.getByText(enUS.q_g2)).toBeTruthy();
  expect(screen.getByText(enUS.q_g3Ok)).toBeTruthy();
  expect(screen.getByTestId("quant-lag").textContent).toBe(enUS.q_lagOk);
  // Every chart is present.
  for (const title of [
    enUS.q_mainTitle,
    enUS.q_brTitle,
    enUS.q_bkTitle,
    enUS.q_stTitle,
    enUS.q_micTitle,
    enUS.q_flowTitle,
    enUS.q_msTitle,
  ])
    expect(screen.getAllByLabelText(title).length).toBeGreaterThan(0);
  // Signal logs and the base-rate table carry the data's own names.
  expect(screen.getAllByText(quant.sig[0][1]).length).toBeGreaterThan(0);
  expect(screen.getAllByText(quant.msig[0][1]).length).toBeGreaterThan(0);
  expect(screen.getAllByText("M4 二波失败").length).toBeGreaterThan(0);
});

test("the main chart carries the lines, state bands, switch marks and signal markers", async () => {
  await mount(backend(), { path: "/quant" });
  await screen.findByLabelText(enUS.q_leadTitle);
  const o = chartOption(enUS.q_mainTitle);
  const names = o.series.map((s: { name: string }) => s.name);
  expect(names.slice(0, 4)).toEqual([
    enUS.q_sLead,
    enUS.q_sDef,
    enUS.q_sBreadth,
    enUS.q_sSwitch,
  ]);
  // One scatter per signal, named as in the data.
  expect(names.slice(4)).toEqual(quant.sigs.map((s) => s.name));
  expect(o.xAxis.data).toEqual(quant.dmain);
  expect(o.yAxis[1]).toMatchObject({ min: 0, max: 100 });
  const area = o.series[2].markArea.data;
  expect(area).toHaveLength(quant.stband.length);
  expect(area[0][0]).toMatchObject({ yAxis: 0, xAxis: quant.stband[0].x0 });
  expect(area[0][1]).toMatchObject({ yAxis: 3 });
  expect(o.series[3].data).toHaveLength(quant.stmark.length);
  expect(o.series[3].data[0].value).toEqual([
    quant.stmark[0].d,
    3.6,
    quant.stmark[0].st,
  ]);
});

test("ladder charts rebase NAV to the window start; micro charts use the data's markers", async () => {
  await mount(backend(), { path: "/quant" });
  await screen.findByLabelText(enUS.q_leadTitle);
  const step = chartOption(enUS.q_stTitle);
  expect(step.series[1].data[0]).toBe(1);
  expect(step.series[2].data[0]).toBe(1);
  expect(step.series[0].step).toBe("end");
  expect(step.series[0].data).toEqual(quant.step.posa);
  const micro = chartOption(enUS.q_micTitle);
  expect(micro.series[0].markArea.data).toEqual(quant.mareas);
  expect(micro.series.slice(3).map((s: { name: string }) => s.name)).toEqual(
    quant.msigs.map((s) => s.name),
  );
  const flow = chartOption(enUS.q_flowTitle);
  expect(flow.series[0].type).toBe("bar");
  expect(flow.series[2].yAxisIndex).toBe(1);
  expect(chartOption(enUS.q_brTitle).series[1].markLine.data[0].yAxis).toBe(20);
});

test("pure helpers: rebase, the history filter and the main tooltip", () => {
  expect(rebase([null, 2, 4, null])).toEqual([null, 1, 2, null]);
  const h: HistTuple[] = [
    ["d1", "A", 1, 1, 1, 25, 25, ""],
    ["d2", "A", 1, 1, 1, 25, 25, ""],
    ["d3", "A", 1, 1, 1, 50, 25, "M1 过热|V 底部确认"],
    ["d4", "B", 1, 1, 1, 50, 25, ""],
    ["d5", "B", 1, 1, 1, 50, 25, ""],
  ];
  expect(histRows(h, false)).toHaveLength(5);
  // Changed days (d3 position, d4 state) and the latest day stay.
  const only = histRows(h, true);
  expect(only.map((r) => r.date)).toEqual(["d3", "d4", "d5"]);
  expect(only[0]).toMatchObject({ stepDir: 1, sigs: "M1 过热 · V 底部确认" });
  expect(only[1].stepDir).toBe(0);
  const tip = mainTooltip(
    enUS,
    [["<b>x</b>", 25, null, 8.4, -7.3, 3.9]],
    [
      {
        axisValue: "2026-01-05",
        dataIndex: 0,
        seriesName: enUS.q_sLead,
        color: "#f00",
        value: 102.2,
      },
      {
        axisValue: "2026-01-05",
        dataIndex: 0,
        seriesName: "M1 过热",
        seriesType: "scatter",
        color: "#0f0",
        value: [],
      },
    ],
  );
  expect(tip).toContain("2026-01-05");
  // The day block comes from dayinfo and the state is escaped.
  expect(tip).toContain("&#60;b&#62;x&#60;/b&#62;");
  expect(tip).toContain("25%");
  expect(tip).toContain(`${enUS.q_sLead}: 102.2`);
  expect(tip).toContain(fill(enUS.q_tipFired, { name: "M1 过热" }));
});

test("the state table filters to change days, pages by 20 and resets to page 1", async () => {
  await mount(backend(), { path: "/quant" });
  const count = await screen.findByTestId("hist-count");
  const total = quant.mon.hist.length;
  const shown = (n: number) => fill(enUS.q_histCount, { shown: n, total });
  expect(count.textContent).toBe(shown(total));
  const panel = count.closest(".ant-card") as HTMLElement;
  const bodyRows = () =>
    panel.querySelectorAll("tbody tr.ant-table-row").length;
  // 60 rows, 20 per page: three pages, newest first.
  expect(bodyRows()).toBe(20);
  expect(panel.querySelectorAll(".ant-pagination-item")).toHaveLength(3);
  expect(
    panel.querySelector("tbody tr.ant-table-row td")!.textContent,
  ).toContain(quant.asof.slice(5));
  fireEvent.click(panel.querySelector(".ant-pagination-item-2")!);
  await waitFor(() =>
    expect(panel.querySelector(".ant-pagination-item-2")!.className).toContain(
      "active",
    ),
  );
  // Filtering keeps only days where the state or a position changed (plus the latest).
  fireEvent.click(within(panel).getByLabelText(enUS.q_histOnlyChg));
  const expected = histRows(quant.mon.hist as HistTuple[], true).length;
  expect(expected).toBeLessThan(20);
  await waitFor(() =>
    expect(screen.getByTestId("hist-count").textContent).toBe(shown(expected)),
  );
  expect(bodyRows()).toBe(expected);
  expect(panel.querySelector(".ant-pagination")).toBeNull();
  fireEvent.click(within(panel).getByLabelText(enUS.q_histOnlyChg));
  await waitFor(() => expect(bodyRows()).toBe(20));
  expect(panel.querySelector(".ant-pagination-item-1")!.className).toContain(
    "active",
  );
});

test("the methodology collapses and expands, and carries the live numbers", async () => {
  await mount(backend(), { path: "/quant" });
  const header = (await screen.findByText(enUS.q_methodTitle)).closest(
    "[role=button]",
  ) as HTMLElement;
  expect(header.getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByText(enUS.qm_h1)).toBeNull();
  fireEvent.click(header);
  expect(await screen.findByText(enUS.qm_h1)).toBeTruthy();
  expect(header.getAttribute("aria-expanded")).toBe("true");
  // The ladder backtest cells are filled from step.stat, not left as placeholders.
  const cagr = quant.step.stat.hold.cagr;
  const holdRow = document.querySelector(
    '[data-table="t6c"] tbody tr',
  ) as HTMLElement;
  expect(holdRow.textContent).toContain(`${cagr}%`);
  expect(document.body.textContent).not.toMatch(/\{\w+\}/);
  // The delisted count (used, not meta) goes into both places that name it.
  const used = String(quant.delisted.used);
  expect(
    document.querySelector('[data-table="t3"] tbody tr')!.textContent,
  ).toContain(used);
  expect(
    screen.getAllByText(
      (_, el) =>
        !!el &&
        el.tagName === "TD" &&
        !!el.textContent?.includes(`excludes ${used} delisted`),
    ).length,
  ).toBe(1);
  expect(document.body.textContent).not.toContain("169");
  fireEvent.click(header);
  await waitFor(() =>
    expect(header.getAttribute("aria-expanded")).toBe("false"),
  );
});

test("a missing delisted field shows a dash instead of a number", async () => {
  const { delisted: _drop, ...without } = quant;
  void _drop;
  await mount(backend({ summary: { quant: without } }), { path: "/quant" });
  fireEvent.click(
    (await screen.findByText(enUS.q_methodTitle)).closest(
      "[role=button]",
    ) as HTMLElement,
  );
  expect((await screen.findAllByText(enUS.qm_h3)).length).toBeGreaterThan(0);
  expect(
    document.querySelector('[data-table="t3"] tbody tr')!.textContent,
  ).toContain("including — delisted stocks");
});

test("the quant page renders in Chinese and the lag tone follows the estimate rule", async () => {
  const stale = {
    ...quant,
    mon: { ...quant.mon, lag: 1, expectSrc: "weekday" },
  };
  await mount(backend({ summary: { quant: stale } }), {
    path: "/quant",
    locale: "zh-CN",
  });
  const lag = await screen.findByTestId("quant-lag");
  expect(lag.textContent).toBe(
    fill(zhCN.q_lagBehind, { n: 1 }) + zhCN.q_estimated,
  );
  // Estimated lag is yellow, not the danger red.
  expect(document.querySelector('[data-tone="none"]')).not.toBeNull();
  expect(document.querySelector('[data-tone="hit"]')).not.toBeNull();
});

test("overview shows the quant card from summary.quant and renders nothing without it", async () => {
  const q = {
    as_of: "2026-11-23",
    state: "熊市确认（主跌延续）",
    state_code: "bad",
    breadth: 8.4,
    ndr: -7.3,
    step_pos: 25,
    step_stage: 1,
    step_cap: false,
    micro_state: "深跌区（偏买）",
    micro_code: "ok",
    micro_pos: 25,
  };
  const app = await mount(withQuant(q), { path: "/" });
  expect(await screen.findByText(enUS.ov_quant)).toBeTruthy();
  const card = screen
    .getByText(enUS.ov_quant)
    .closest(".ant-card") as HTMLElement;
  expect(within(card).getByText(q.state)).toBeTruthy();
  expect(within(card).getByText(enUS.q_tag_bad)).toBeTruthy();
  expect(within(card).getByText(q.micro_state)).toBeTruthy();
  expect(within(card).getByText(enUS.q_tag_ok)).toBeTruthy();
  expect(
    within(card).getByText(
      fill(enUS.ov_quantStats, {
        b: "8.4",
        n: "-7.3",
        stage: 1,
        pos: 25,
        cap: "",
      }),
    ),
  ).toBeTruthy();
  expect(
    within(card).getByText(fill(enUS.ov_quantMicro, { pos: 25 })),
  ).toBeTruthy();
  fireEvent.click(within(card).getByText(enUS.ov_quantOpen));
  await waitFor(() =>
    expect(app.calls.some((c) => c.startsWith("/v1/quant/"))).toBe(true),
  );
});

test("overview without summary.quant has no quant card, and the dashboards list links to quant", async () => {
  await mount(backend(), { path: "/" });
  expect(await screen.findByText(enUS.ov_dashboards)).toBeTruthy();
  expect(screen.queryByText(enUS.ov_quant)).toBeNull();
  expect(screen.getAllByText(enUS.nav_quant).length).toBeGreaterThan(0);
});
