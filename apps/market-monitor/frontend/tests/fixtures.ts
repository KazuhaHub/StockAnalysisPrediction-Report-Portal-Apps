import { type Handler, ok, noData, notFound } from "./harness";

export const marginRows = Array.from({ length: 45 }, (_, i) => ({
  code: String(600000 + i),
  name: `Stock${i}`,
  price: 10 + i,
  chg: i % 2 ? 1.2 : -0.8,
  ratio: 1 + i / 10,
  frag: 90 - i,
  state: i % 3 ? "安全" : "临界",
  level: "正常",
  tags: i % 5 === 0 ? "价跌加杠杆|占比畸高" : "",
  cost: 11,
  pld_ratio: null,
}));

const histDates = Array.from({ length: 60 }, (_, i) => `d${i}`);

export const summaries: Record<string, unknown> = {
  risk: {
    margin: {
      as_of: "2026-11-16",
      lever_ratio: 4.1,
      guarantee: 255.5,
      lever_series: { d: ["a", "b"], rz: [1, 2], ratio: [4, 4.1] },
      guarantee_series: { d: ["a", "b"], v: [250, 255] },
      n_res2: 85,
      n_critical: 556,
    },
    sentiment: {
      as_of: "2026-11-16",
      headline: "Cold signal on day 23",
      breadth: 14.4,
      breadth_series: { dates: ["a", "b"], values: [15, 14.4] },
    },
    etf: {
      as_of: "2026-11-16",
      current: { last20: 2832 },
      health: { label: "失效", light: "red" },
      nf_series: { dates: ["a", "b"], nf: [1, 2] },
    },
    inputs: {
      margin: "2026-11-16",
      sentiment: "2026-11-16",
      etf: "2026-11-16",
    },
  },
  margin: {
    meta: { assumptions: { k_call: 0.667, k_liq: 0.578 } },
    hist_dates: histDates,
    overview: {
      rz_total: 20885,
      rq_total: 219,
      n_total: 3526,
      ratio_med: 4.2,
      ratio_p90: 8.2,
      ratio_p99: 12.3,
      n_critical: 556,
      n_latent: 260,
      n_flushed: 354,
      n_high: 358,
      n_watch: 127,
      n_pledge: 925,
      n_pledge_breach: 49,
      res_hist: [
        { k: 0, n: 5 },
        { k: "4+", n: 0 },
      ],
    },
  },
  sentiment: {
    asof: "2026-11-16",
    headline: "Breadth stays cold",
    conclusion: { v: 29.7 },
    disp: { v: 27, rank: 74 },
    dims: [
      {
        k: "广度",
        desc: "breadth",
        v: 14.4,
        d1: 13,
        d5: 25,
        d20: 16,
        verdict: "ok",
      },
    ],
    grid: {
      x: ["低", "高"],
      y: ["a", "b"],
      cells: [
        [
          { v: null, n: 1 },
          { v: 1.5, n: 2, cur: true },
        ],
        [
          { v: -1, n: 3 },
          { v: 2, n: 4 },
        ],
      ],
    },
    signal: {
      days: 23,
      trigger: "2026-10-15",
      ret_since: -5.5,
      hist_n: 19,
      hist_med20: 4.6,
      hist_win20: 84,
      path: [0, 1],
      cur_path: [0, 0.5],
    },
    alerts: [
      { level: "green", title: "Favourable cell", body: "median <b>+2%</b>" },
    ],
    extreme: [{ name: "Limit down", v: "78", pct: 97 }],
    traj: { dates: ["a", "b"], series: { 广度: [70, 71] } },
  },
  etf: {
    current: {
      last_date: "2026-11-16",
      last_nf: 136.8,
      last5: -178,
      last20: 2832,
      ytd: -8314,
      idx_20d: -3.4,
    },
    health: {
      light: "red",
      label: "失效",
      items: [{ k: "Nature", v: "β=-40", note: "n", s: -2 }],
    },
    runs_top: [{ start: "2024-01-16", end: "2024-02-19", days: 19, sum: 2568 }],
    series: {
      dates: ["2026-11-13", "2026-11-16"],
      nf: [1, 2],
      nf_ma20: [null, 1],
      idx: [3500, 3600],
    },
    broad: {
      dates: ["2026-11-13", "2026-11-16"],
      cats: ["沪深300", "科创50"],
      series: { 沪深300: [1, 2], 科创50: [3, 4] },
    },
    scope: { universe: "SH broad ETFs", n_codes: 203, note: "note" },
    data_health: { share_last: "2026-11-16" },
  },
  panorama: {
    meta: {
      report_period: "2026Q3",
      n_universe: 5588,
      n_valid: 4590,
      n_pool: 5511,
      n_factors: 54,
      labels: { 合理: 1999, 低估: 503 },
      quads: { 便宜好公司: 362, 优质但贵: 2411, 价值陷阱: 587, 又贵又差: 2146 },
      profiles: { 均衡: 3892 },
      coverage: { value: { n: 5588, mean: 0.88 } },
    },
    factors: [{ id: "EP", name: "EP factor" }],
    strategies: {
      value: {
        name: "价值",
        desc: "buy cheap",
        w: { EP: 20 },
        templates: [{ id: "V1", name: "Deep value", desc: "d", n: 550 }],
      },
    },
    methods: [{ id: "PE_REL", name: "Relative PE", weight: 1, cov: 3302 }],
  },
};

const panoramaRows = Array.from({ length: 30 }, (_, i) => ({
  code: String(1 + i).padStart(6, "0"),
  name: `Pano${i}`,
  sw1: "银行",
  label: "合理",
  quad: "优质但贵",
  profile: "均衡",
  price: 12.3,
  composite: 14,
  upside: 0.1,
  pe: 5,
  pb: 0.4,
  roe: 7,
  n_methods: 3,
  s_value: 80 - i,
  s_growth: 70,
  s_cyclical: 60,
  s_dividend: 50,
  s_momentum: 40,
  s_quality: 30,
  v_PE_REL: 13,
}));
const etfRows = [
  {
    code: "588000",
    name: "STAR50 ETF",
    cat: "科创50",
    cum20: 414.6,
    cum_ytd: 694.8,
  },
  // A category the summary's broad.cats list does not carry.
  {
    code: "159000",
    name: "CNI2000 ETF",
    cat: "国证2000",
    cum20: 1,
    cum_ytd: 2,
  },
];
const rowsOf: Record<string, Record<string, unknown>[]> = {
  margin: marginRows,
  panorama: panoramaRows,
  etf: etfRows,
};

export type Options = {
  dates?: Record<string, string[]>;
  /** Replaces a module's scripted rows. */
  rows?: Record<string, Record<string, unknown>[]>;
  failRuns?: boolean;
  /** Replaces a module's scripted summary. */
  summary?: Record<string, unknown>;
};

/** A scripted backend: pages the in-memory rows only by page and size. */
export function backend(options: Options = {}): Handler {
  return (path, params) => {
    const parts = path.replace("/v1/", "").split("/");
    if (parts[0] === "runs")
      return options.failRuns
        ? { status: 409, body: { error: "unavailable" } }
        : ok({
            runs: [
              {
                id: "r1",
                job: "margin",
                status: "succeeded",
                attempt: 1,
                queued_at: "2026-11-17T01:00:00Z",
                finished_at: "2026-11-17T01:05:00Z",
              },
            ],
          });
    const module = parts[0];
    const dates = options.dates?.[module] ?? ["2026-11-16", "2026-11-13"];
    if (parts[1] === "dates") return ok({ module, dates });
    if (dates.length === 0) return noData;
    if (parts[1] === "summary")
      return ok({
        module,
        as_of: params.get("date") ?? dates[0],
        summary: options.summary?.[module] ?? summaries[module],
      });
    const rows = options.rows?.[module] ?? rowsOf[module] ?? [];
    if (parts[1] === "rows" && parts[2]) {
      const row = rows.find((r) => r.code === parts[2]);
      if (!row) return notFound;
      const detail =
        module === "margin"
          ? {
              c: Array.from({ length: 60 }, (_, i) => 10 + i / 10),
              r: Array.from({ length: 60 }, () => 1),
            }
          : null;
      return ok({ module, as_of: dates[0], row, detail });
    }
    if (parts[1] === "rows") {
      const page = Number(params.get("page") ?? 1);
      const size = Number(params.get("size") ?? 50);
      return ok({
        module,
        as_of: dates[0],
        page,
        size,
        total: rows.length,
        items: rows.slice((page - 1) * size, page * size),
      });
    }
    return notFound;
  };
}
