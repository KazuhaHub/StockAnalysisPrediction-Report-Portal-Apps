import type { Copy } from "./copy";
import { escapeHtml } from "./html";
import { DASH, arr, fill, isNum, type Num } from "./format";

/** One summary of the quant module, as the pipeline writes it. */
export type QuantStat = {
  cagr?: Num;
  dd?: Num;
  calmar?: Num;
  pos?: Num;
  ret?: Num;
};
export type SignalSeries = {
  name: string;
  color: string;
  sym: string;
  rot: number;
  size: number;
  pts: [string, number][];
};
/** [date, state, breadth, breadth pctile 250, NDR, tech position, micro position, "sig|sig"]. */
export type HistTuple = [
  string,
  string,
  Num,
  Num,
  Num,
  Num,
  Num,
  string | null,
];
export type QuantRun = {
  date?: string;
  at?: string;
  status: string;
  asof?: string;
  note?: string;
};
export type BaseRate = {
  n: number;
  win?: Num;
  med?: Num;
  exc?: Num;
  dd10?: Num;
  meddd?: Num;
};
export type LadderStep = {
  stage: number;
  pos: number;
  diag: { sw: Num; med: Num; short: Num };
  eq: Num[];
  hold: Num[];
  posa: Num[];
};
export type QuantSummary = {
  asof: string;
  gen?: string;
  mon: {
    expect?: string | null;
    expectSrc?: string;
    lag: Num;
    days: number;
    prevDays: number;
    cover: number;
    locked?: { update?: Num; write?: Num };
    hist: HistTuple[];
    chg?: {
      step?: [Num, Num];
      mic?: [Num, Num];
      state?: [string, string];
    };
    runs?: QuantRun[];
    today?: { sigs?: string[] };
    tdN?: Num;
  };
  state: string;
  stateCode: string;
  b: number;
  bpct: Num;
  ndr: number;
  npct: Num;
  rep20: number;
  dd250: number;
  dd60: number;
  r60lead: number;
  r60def: number;
  since: Record<string, Num>;
  dmain: string[];
  lead: Num[];
  def: Num[];
  breadth: Num[];
  stband: { x0: string; x1: string; st: string; color: string }[];
  stmark: { d: string; st: string; color: string }[];
  dayinfo: [string, Num, Num, Num, Num, Num][];
  dbr: string[];
  breadth2: Num[];
  ndr2: Num[];
  bA20: Num[];
  bA60: Num[];
  bA200: Num[];
  leadX: Num[];
  sigs: SignalSeries[];
  sig: [string, string, string][];
  base: Record<string, BaseRate>;
  mstate: string;
  mcode: string;
  mb: number;
  mbpct: Num;
  mshare: number;
  msdrop: number;
  md60: number;
  mrs: number;
  mrsm: number;
  mdd250: number;
  mr60: number;
  dmw: string[];
  mic: Num[];
  mew: Num[];
  mbw: Num[];
  msh: Num[];
  mrsn: Num[];
  msig: [string, string, string][];
  msigs: SignalSeries[];
  mfsigs: SignalSeries[];
  mareas: [{ xAxis: string }, { xAxis: string }][];
  deepNow: boolean;
  deepDays: Num;
  deepSeg?: [string, string] | null;
  deepst: {
    n: Num;
    n60: Num;
    med60: Num;
    win60: Num;
    med120: Num;
    win120: Num;
    lastStart?: string;
    lastLen?: Num;
  };
  mstep: LadderStep & {
    bear: boolean;
    over: boolean;
    dma200: number;
    belowDays: Num;
    up: number;
    holdN: Num;
    px: number;
    ma200: number;
    stat: Record<
      "all" | "hold" | "out" | "outH" | "y24" | "y24H" | "y26" | "y26H",
      QuantStat
    >;
  };
  vstat: {
    all: { n: Num; med: Num; win: Num };
    out: { n: Num; med?: Num; win: Num };
  };
  flowstat: { n: Num; med: Num; win: Num };
  msince: Record<string, Num>;
  step: LadderStep & {
    cap: boolean;
    capr: string;
    band: number;
    holdN: Num;
    px60: number;
    bq: Num;
    rep: number;
    stat: Record<"all" | "hold" | "out" | "y26" | "y26h", QuantStat>;
  };
  /** Delisted stocks: `meta` the store marks, `used` the ones that enter the computations. */
  delisted?: { meta?: Num; used?: Num };
};

/** Signed value as the pipeline wrote it (no rounding), or the dash. */
export function sg(v: Num): string {
  return isNum(v) ? (v > 0 ? "+" : "") + String(v) : DASH;
}
/** Plain number as written, or the dash. */
export function nv(v: Num): string {
  return isNum(v) ? String(v) : DASH;
}

/** antd Tag colour of a state code: ok / warn / cold / bad / neutral. */
export const TAG_COLOR: Record<string, string> = {
  cold: "processing",
  bad: "error",
  warn: "warning",
  ok: "success",
  neutral: "default",
};

/** Display text of a state code (a closed set the pipeline writes). */
export function tagText(copy: Copy, code: string): string {
  const key = `q_tag_${code}` as keyof Copy;
  return key in copy ? copy[key] : copy.q_tag_neutral;
}

/** The sub-state of a state label, by the Chinese words the pipeline writes. */
export type Tone = "info" | "danger" | "warning" | "success";
export function stateTone(state: string): Tone {
  if (state.includes("出清") || state.includes("确认区")) return "info";
  if (state.includes("熊市") || state.includes("下跌")) return "danger";
  if (state.includes("警戒") || state.includes("过热")) return "warning";
  return "success";
}

const FSM_PREFIXES = [
  "过热",
  "顶部警戒",
  "下跌中",
  "熊市确认",
  "出清区",
  "确认区",
  "修复区",
];
/** Index (0-7) of the state-machine step a state label belongs to; 0 is the default. */
export function fsmIndex(state: string): number {
  let act = 0;
  FSM_PREFIXES.forEach((p, i) => {
    if (state.startsWith(p)) act = i + 1;
  });
  return act;
}

/** The signal that fired most recently: [name, days ago]. */
export function nearestSince(
  since: Record<string, Num> | undefined,
): [string, number] | null {
  let best: [string, number] | null = null;
  for (const [name, days] of Object.entries(since ?? {}))
    if (isNum(days) && (!best || days < best[1])) best = [name, days];
  return best;
}

export type HistRow = {
  date: string;
  state: string;
  breadth: Num;
  bq: Num;
  ndr: Num;
  step: Num;
  mic: Num;
  sigs: string;
  /** Tech position moved up (1) or down (-1) against the previous day. */
  stepDir: 1 | -1 | 0;
  changed: boolean;
};

/**
 * The daily state rows, oldest first. With `onlyChanges` a row stays only if
 * its state or either position differs from the previous day's, or it is the
 * latest row (the reference's filter).
 */
export function histRows(hist: HistTuple[], onlyChanges: boolean): HistRow[] {
  const rows: HistRow[] = [];
  let prev: HistTuple | null = null;
  hist.forEach((r, idx) => {
    const [date, state, breadth, bq, ndr, step, mic, sigs] = r;
    const changed =
      !!prev && (prev[1] !== state || prev[5] !== step || prev[6] !== mic);
    const last = idx === hist.length - 1;
    const before = prev;
    prev = r;
    if (onlyChanges && !changed && !last) return;
    rows.push({
      date,
      state,
      breadth,
      bq,
      ndr,
      step,
      mic,
      sigs: sigs ? sigs.split("|").join(" · ") : "",
      stepDir:
        before && isNum(step) && isNum(before[5]) && step !== before[5]
          ? step > before[5]
            ? 1
            : -1
          : 0,
      changed,
    });
  });
  return rows;
}

/** A NAV series rebased to its first positive value, as the reference draws it. */
export function rebase(values: Num[]): Num[] {
  const first = values.find((x) => isNum(x) && x > 0);
  return values.map((x) =>
    isNum(x) && isNum(first) ? +(x / first).toFixed(4) : null,
  );
}

type TipParam = {
  axisValue?: string;
  axisValueLabel?: string;
  dataIndex: number;
  seriesName: string;
  seriesType?: string;
  color?: unknown;
  value?: unknown;
};
const dot = (color: unknown, glyph: string) =>
  `<span style="color:${escapeHtml(color)}">${glyph}</span>`;

/** Tooltip of the main chart: the day's state block from `dayinfo`, then the series. */
export function mainTooltip(
  copy: Copy,
  dayinfo: QuantSummary["dayinfo"],
  params: TipParam[],
): string {
  if (!params.length) return "";
  const head = `<b>${escapeHtml(params[0].axisValue)}</b>`;
  const di = dayinfo[params[0].dataIndex];
  const pos = (x: Num) => (isNum(x) ? `${x}%` : DASH);
  const info = di
    ? `<div style="margin:3px 0 5px;line-height:1.7">${escapeHtml(
        fill(copy.q_tipState, {
          state: di[0],
          step: pos(di[1]),
          mic: pos(di[2]),
        }).replace(/\*\*/g, ""),
      )}<br/>${escapeHtml(
        fill(copy.q_tipBreadth, {
          b: nv(di[3]),
          p: isNum(di[5]) ? `${di[5]}` : DASH,
          n: nv(di[4]),
        }),
      )}</div>`
    : "";
  const rows = params.map((p) => {
    if (p.seriesName === copy.q_sSwitch) {
      const st = Array.isArray(p.value) ? p.value[2] : "";
      return `${dot(p.color, "▲")} ${escapeHtml(fill(copy.q_tipSwitch, { st: String(st) }))}`;
    }
    if (p.seriesType === "scatter")
      return `${dot(p.color, "◆")} ${escapeHtml(fill(copy.q_tipFired, { name: p.seriesName }))}`;
    return `${dot(p.color, "●")} ${escapeHtml(p.seriesName)}: ${p.value == null ? DASH : escapeHtml(p.value)}`;
  });
  return head + info + rows.join("<br/>");
}

/** Generic axis tooltip: scatter marks as "fired", empty values dropped, `%` on named series. */
export function seriesTooltip(
  copy: Copy,
  params: TipParam[],
  percent: string[],
): string {
  if (!params.length) return "";
  const rows = params
    .filter((p) => p.seriesType === "scatter" || p.value != null)
    .map((p) =>
      p.seriesType === "scatter"
        ? `${dot(p.color, "◆")} ${escapeHtml(fill(copy.q_tipFired, { name: p.seriesName }))}`
        : `${dot(p.color, "●")} ${escapeHtml(p.seriesName)}: ${escapeHtml(p.value)}${
            percent.includes(p.seriesName) ? "%" : ""
          }`,
    );
  return `<b>${escapeHtml(params[0].axisValue)}</b><br/>${rows.join("<br/>")}`;
}

export const hasItems = <T>(v: T[] | null | undefined) => arr(v).length > 0;
