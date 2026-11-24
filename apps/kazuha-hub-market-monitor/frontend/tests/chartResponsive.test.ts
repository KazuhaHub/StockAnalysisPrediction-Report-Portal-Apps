import { describe, expect, test } from "vitest";
import {
  COMPACT_WIDTH,
  isCompact,
  responsiveHeight,
  responsiveOption,
  shortDate,
} from "../src/lib/chartResponsive";

type Obj = Record<string, any>;

const dates = ["2026-11-20", "2026-11-23", "2026-11-24"];
const dual = (): Obj => ({
  tooltip: { trigger: "axis" },
  legend: { top: 0 },
  grid: { left: 50, right: 64, top: 36, bottom: 30 },
  xAxis: { type: "category", data: dates },
  yAxis: [
    { type: "value", name: "Net flow (100M CNY)" },
    { type: "value", name: "Index (CSI 300)", scale: true },
  ],
  dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }],
  series: [
    { type: "bar", data: [1, 2, 3], itemStyle: { color: "#f00" } },
    {
      type: "line",
      yAxisIndex: 1,
      data: [3, 2, 1],
      lineStyle: { color: "#00f" },
    },
  ],
});

const phone = 360;

function deepFreeze<T>(x: T): T {
  if (x && typeof x === "object") {
    Object.values(x).forEach(deepFreeze);
    Object.freeze(x);
  }
  return x;
}

/** Every colour-bearing value in an option, by path. */
function colours(x: unknown, path = "", out: Record<string, unknown> = {}) {
  if (x && typeof x === "object")
    for (const [k, v] of Object.entries(x)) {
      const p = `${path}.${k}`;
      if (/color/i.test(k) && typeof v !== "object") out[p] = v;
      else colours(v, p, out);
    }
  return out;
}

describe("responsiveOption", () => {
  test("leaves a wide or unmeasured container alone, by reference", () => {
    const option = dual();
    expect(responsiveOption(option, COMPACT_WIDTH)).toBe(option);
    expect(responsiveOption(option, 1200)).toBe(option);
    expect(responsiveOption(option, 0)).toBe(option);
    expect(isCompact(COMPACT_WIDTH - 1)).toBe(true);
    expect(isCompact(0)).toBe(false);
  });

  test("never mutates its input", () => {
    const option = deepFreeze(dual());
    expect(() => responsiveOption(option, phone)).not.toThrow();
  });

  test("gives the legend a scrolling row of its own and starts the grid below it", () => {
    const out = responsiveOption(dual(), phone);
    expect(out.legend.type).toBe("scroll");
    // One legend row plus the named value axes' names above the plot.
    expect(out.grid.top).toBeGreaterThanOrEqual(52);
    const plain = responsiveOption(
      { ...dual(), yAxis: { type: "value" }, series: [] },
      phone,
    );
    expect(plain.grid.top).toBeGreaterThanOrEqual(34);
    // A taller reservation the page already made is kept.
    const tall = responsiveOption({ ...dual(), grid: { top: 90 } }, phone);
    expect(tall.grid.top).toBe(90);
  });

  test("keeps a bottom legend below the axis labels", () => {
    const out = responsiveOption(
      {
        legend: { bottom: 0 },
        grid: { left: 40, right: 10, top: 20, bottom: 28 },
        xAxis: { type: "category", data: ["a"] },
        yAxis: { type: "value" },
        series: [],
      },
      phone,
    );
    expect(out.grid.bottom).toBeGreaterThanOrEqual(60);
    expect(out.grid.top).toBe(20);
  });

  test("moves a vertical legend into the row", () => {
    const out = responsiveOption(
      { legend: { orient: "vertical", right: 0 }, series: [] },
      phone,
    );
    expect(out.legend.orient).toBe("horizontal");
    expect(out.legend.right).toBeUndefined();
  });

  test("thins axis labels and shortens ISO dates, unless the page chose", () => {
    const out = responsiveOption(dual(), phone);
    expect(out.xAxis.axisLabel.hideOverlap).toBe(true);
    expect(out.xAxis.axisLabel.formatter("2026-11-24")).toBe("11-24");
    expect(shortDate("P90")).toBe("P90");
    expect(shortDate(12)).toBe("12");
    const bins = responsiveOption(
      { xAxis: { type: "category", data: ["0-5", "5-10"] }, series: [] },
      phone,
    );
    expect(bins.xAxis.axisLabel.formatter).toBeUndefined();
    const chosen = responsiveOption(
      {
        xAxis: {
          type: "category",
          data: dates,
          axisLabel: { interval: 0, rotate: 45, formatter: (v: string) => v },
        },
        series: [],
      },
      phone,
    );
    expect(chosen.xAxis.axisLabel.interval).toBe(0);
    expect(chosen.xAxis.axisLabel.rotate).toBe(45);
    expect(chosen.xAxis.axisLabel.formatter("2026-11-24")).toBe("2026-11-24");
  });

  test("keeps both axes of a dual-axis chart, with margins and hanging names", () => {
    const out = responsiveOption(dual(), phone);
    expect(out.yAxis).toHaveLength(2);
    expect(out.grid.left).toBeGreaterThanOrEqual(40);
    expect(out.grid.right).toBeGreaterThanOrEqual(40);
    expect(out.grid.right).toBeLessThanOrEqual(52);
    expect(out.yAxis[0].nameTextStyle.align).toBe("left");
    expect(out.yAxis[1].nameTextStyle.align).toBe("right");
    // The second axis is read from its labels; one set of grid lines remains.
    expect(out.yAxis[0].splitLine).toBeUndefined();
    expect(out.yAxis[1].splitLine).toEqual({ show: false });
    expect(out.yAxis[1].scale).toBe(true);
  });

  test("wraps long category names inside a smaller left margin", () => {
    const out = responsiveOption(
      {
        grid: { left: 130, right: 40, top: 10, bottom: 20 },
        xAxis: { type: "value" },
        yAxis: { type: "category", data: ["a very long strategy name"] },
        series: [],
      },
      phone,
    );
    expect(out.grid.left).toBe(Math.round(phone * 0.28));
    expect(out.yAxis.axisLabel.overflow).toBe("break");
    expect(out.yAxis.axisLabel.width).toBe(out.grid.left - 8);
  });

  test("confines the tooltip, and adds none to a chart without one", () => {
    expect(responsiveOption(dual(), phone).tooltip).toEqual({
      confine: true,
      trigger: "axis",
    });
    expect(
      responsiveOption({ ...dual(), tooltip: undefined }, phone),
    ).toHaveProperty("tooltip", undefined);
    const noTip = dual();
    delete noTip.tooltip;
    expect(responsiveOption(noTip, phone)).not.toHaveProperty("tooltip");
    const own = responsiveOption(
      { tooltip: { confine: false }, series: [] },
      phone,
    );
    expect(own.tooltip.confine).toBe(false);
  });

  test("drops an inside zoom, which would trap the page's scroll, and keeps the slider", () => {
    const out = responsiveOption(dual(), phone);
    expect(out.dataZoom).toEqual([{ type: "slider", height: 18, bottom: 8 }]);
    const only = dual();
    only.dataZoom = [{ type: "inside" }];
    expect(responsiveOption(only, phone)).not.toHaveProperty("dataZoom");
  });

  test("pulls a radar in and keeps pie labels from colliding", () => {
    const out = responsiveOption(
      {
        radar: { indicator: [], radius: "62%" },
        series: [{ type: "pie", label: { formatter: "{b}" }, data: [] }],
      },
      phone,
    );
    expect(out.radar.radius).toBe("56%");
    expect(out.series[0].label.formatter).toBe("{b}");
    expect(out.series[0].labelLayout.hideOverlap).toBe(true);
  });

  test("changes no colour", () => {
    const option = {
      ...dual(),
      series: [
        ...dual().series,
        {
          type: "pie",
          data: [{ name: "a", value: 1, itemStyle: { color: "#abc" } }],
        },
      ],
    };
    const before = colours(option);
    expect(Object.keys(before).length).toBeGreaterThan(2);
    expect(colours(responsiveOption(option, phone))).toEqual(before);
    // The series of a cartesian chart are passed through as they are.
    expect(responsiveOption(dual(), phone).series).toEqual(dual().series);
  });
});

describe("responsiveHeight", () => {
  test("lifts a chart to a reading height on a phone only", () => {
    expect(responsiveHeight(240, phone)).toBe(280);
    expect(responsiveHeight(340, phone)).toBe(340);
    expect(responsiveHeight(240, 900)).toBe(240);
    expect(responsiveHeight(240, 0)).toBe(240);
  });

  test("leaves a sparkline alone", () => {
    expect(responsiveHeight(44, phone)).toBe(44);
  });
});
