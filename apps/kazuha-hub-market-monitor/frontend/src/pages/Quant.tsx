import { useMemo, useState, type ReactNode } from "react";
import {
  Card,
  Checkbox,
  Collapse,
  Empty,
  Space,
  Statistic,
  Table,
  Tag,
} from "antd";
import type { TableColumnsType } from "antd";
import { Dashboard } from "../components/Dashboard";
import { EChart, type ChartOption } from "../components/EChart";
import { KpiRow, type KpiItem } from "../components/Kpi";
import { Panel, Panels } from "../components/Panels";
import { rich } from "../components/Rich";
import { Signed, SignedIn } from "../components/Signed";
import { shown } from "../lib/status";
import { useVisual } from "../components/useVisual";
import { useCopy, type Copy } from "../lib/copy";
import { arr, fill, fmt, isNum, signed, DASH, type Num } from "../lib/format";
import {
  TAG_COLOR,
  fsmIndex,
  histRows,
  mainTooltip,
  nearestSince,
  nv,
  rebase,
  seriesTooltip,
  sg,
  sx,
  stateTone,
  tagText,
  type HistRow,
  type QuantStat,
  type QuantSummary,
  type SignalSeries,
} from "../lib/quant";
import { QuantMethod } from "./QuantMethod";

const PAGE_SIZE = 20;

export function QuantPage() {
  const { copy } = useCopy();
  return (
    <Dashboard<QuantSummary> module="quant" title={copy.quantTitle}>
      {({ summary }) => <QuantBody d={summary} />}
    </Dashboard>
  );
}

const copyText = (copy: Copy, key: string) =>
  (copy as Record<string, string>)[key] ?? key;

function Hint({ children }: { children: string }) {
  return <div className="mm-muted mm-hint-block">{rich(children)}</div>;
}

function Gate({
  tone,
  title,
  value,
  children,
}: {
  tone: "hit" | "out" | "";
  title: string;
  value: string;
  children: ReactNode;
}) {
  const v = useVisual();
  const style =
    // Statuses, not signs: a failed check strong orange, a passed one blue.
    tone === "hit"
      ? { borderColor: v.alert, background: v.fillQuaternary }
      : tone === "out"
        ? { borderColor: v.primary, background: v.fillQuaternary }
        : { borderColor: v.borderStrong };
  return (
    <div className="mm-gate" style={style} data-tone={tone || "none"}>
      <div className="mm-muted">{title}</div>
      <div className="mm-gate-value">{value}</div>
      <div className="mm-muted">{children}</div>
    </div>
  );
}

type Step = { key: string; title: string; value?: string; desc: ReactNode };
function StepStrip({
  steps,
  active,
  label,
  pastBefore,
}: {
  steps: Step[];
  active: number;
  label: string;
  /** Steps before the active one are drawn as past only from this index on. */
  pastBefore: number;
}) {
  const v = useVisual();
  return (
    <div className="mm-steps" role="list" aria-label={label}>
      {steps.map((s, i) => {
        const on = i === active;
        const past = !on && i < active && active >= pastBefore;
        return (
          <div
            key={s.key}
            role="listitem"
            className="mm-step"
            aria-current={on ? "step" : undefined}
            data-state={on ? "active" : past ? "past" : "idle"}
            style={{
              borderColor: on ? v.primary : v.border,
              background: on ? v.fillQuaternary : undefined,
              opacity: past ? 0.6 : 1,
            }}
          >
            <div className="mm-step-title">{s.title}</div>
            {s.value && <div className="mm-step-value">{s.value}</div>}
            <div className="mm-muted">{s.desc}</div>
          </div>
        );
      })}
    </div>
  );
}

function statLine(
  copy: Copy,
  key: "q_stStat" | "q_msStat",
  all: QuantStat,
  hold: QuantStat,
  y: QuantStat,
  yh: QuantStat,
) {
  return fill(copy[key], {
    a: sx(all.cagr),
    add: sx(all.dd),
    ac: nv(all.calmar),
    h: sx(hold.cagr),
    hdd: sx(hold.dd),
    hc: nv(hold.calmar),
    y: sx(y.ret),
    yh: sx(yh.ret),
  });
}

function QuantBody({ d }: { d: QuantSummary }) {
  const { copy, locale } = useCopy();
  const v = useVisual();
  const [onlyChanges, setOnlyChanges] = useState(false);
  const [page, setPage] = useState(1);

  const mon = d.mon;
  const S = d.step;
  const MS = d.mstep;
  const lag = mon.lag;
  const estimated = mon.expectSrc === "weekday";
  // On the estimated basis a holiday reads as "1 day behind": yellow, never red.
  const lagWarn = isNum(lag) && lag > 0 && estimated;
  const lagColor = lag === 0 ? v.primary : lagWarn ? v.orange : v.alert;
  const lagText =
    lag === 0
      ? copy.q_lagOk
      : !isNum(lag)
        ? copy.q_lagUnknown
        : fill(copy.q_lagBehind, { n: lag }) +
          (lagWarn ? copy.q_estimated : "");

  const tagOf = (code: string) => ({
    text: tagText(copy, code),
    color: TAG_COLOR[code] ?? "default",
  });

  // ---- KPI cards ----
  const near = nearestSince(d.since);
  const leadNear = (
    <>
      {rich(fill(copy.q_posTier, { stage: S.stage, pos: S.pos }))}
      {S.cap ? fill(copy.q_capBy, { capr: S.capr }) : ""}
      {near ? fill(copy.q_nearest, { name: near[0], days: near[1] }) : ""}
    </>
  );
  const leadItems: KpiItem[] = [
    {
      key: "b",
      title: copy.q_breadth,
      value: `${fmt(d.b, 1)}%`,
      note: fill(copy.q_pctile, { v: nv(d.bpct) }),
    },
    {
      key: "ndr",
      title: copy.q_ndr,
      value: `${signed(d.ndr, 1)}%`,
      color: v.sign(shown(d.ndr, 1)),
      note: fill(copy.q_pctile, { v: nv(d.npct) }),
    },
    {
      key: "dd",
      title: copy.q_dd250,
      value: `${signed(d.dd250, 1)}%`,
      color: v.sign(shown(d.dd250, 1)),
      note: <SignedIn template={copy.q_dd60} value={d.dd60} />,
    },
    {
      key: "rep",
      title: copy.q_rep20,
      value: `${signed(d.rep20, 1)}pp`,
      color: v.sign(shown(d.rep20, 1)),
      note: copy.q_repThr,
    },
    {
      key: "def",
      title: copy.q_def60,
      value: `${signed(d.r60def, 1)}%`,
      color: v.sign(shown(d.r60def, 1)),
      note: <SignedIn template={copy.q_leadSame} value={d.r60lead} />,
    },
  ];
  const mnear = nearestSince(d.msince);
  const microNear = (
    <>
      {rich(fill(copy.q_mPosTier, { pos: MS.pos }))}
      {MS.bear ? copy.q_mBear : MS.over ? copy.q_mOver : copy.q_mBull}
      {" · "}
      {mnear
        ? fill(copy.q_mNearest, { name: mnear[0], days: mnear[1] })
        : copy.q_mNoSig}
    </>
  );
  const microItems: KpiItem[] = [
    {
      key: "mb",
      title: copy.q_mBreadth,
      value: `${fmt(d.mb, 1)}%`,
      note: fill(copy.q_pctile, { v: nv(d.mbpct) }),
    },
    {
      key: "share",
      title: copy.q_mShare,
      value: `${fmt(d.mshare, 2)}%`,
      note: <SignedIn template={copy.q_mShareNote} value={d.msdrop} />,
    },
    {
      key: "d60",
      title: copy.q_mDist60,
      value: `${signed(d.md60, 1)}%`,
      color: v.sign(shown(d.md60, 1)),
      note: <SignedIn template={copy.q_mDd250} value={d.mdd250} />,
    },
    {
      key: "rs",
      title: copy.q_mRs,
      value: `${signed(d.mrs, 1)}pp`,
      color: v.sign(shown(d.mrs, 1)),
      note: <SignedIn template={copy.q_mRsNote} value={d.mrsm} />,
    },
    {
      key: "r60",
      title: copy.q_mR60,
      value: `${signed(d.mr60, 1)}%`,
      color: v.sign(shown(d.mr60, 1)),
      note: <SignedIn template={copy.q_leadSame} value={d.r60lead} />,
    },
  ];
  const stateCard = (
    state: string,
    code: string,
    note: ReactNode,
    label: string,
  ) => (
    <Card size="small" className="mm-kpi mm-state" aria-label={label}>
      <Statistic title={copy.q_cur} value={state} />
      <div>
        <Tag color={tagOf(code).color}>{tagOf(code).text}</Tag>
        <span className="mm-muted">{note}</span>
      </div>
    </Card>
  );
  const kpiCols = { xs: 12, md: 8, lg: 12, xl: 8 };

  // ---- state machine ----
  const fsmSteps: Step[] = Array.from({ length: 8 }, (_, i) => ({
    key: String(i),
    title: copyText(copy, `q_fsm${i}`),
    desc: rich(copyText(copy, `q_fsm${i}d`)),
  }));

  // ---- daily monitoring ----
  const run = arr(mon.runs)[0] ?? null;
  const runOk = run ? run.status === "ok" : null;
  const runLabel = (status: string) => {
    const key = `q_run_${status}`;
    return Object.hasOwn(copy, key) ? copyText(copy, key) : status;
  };
  const locked = mon.locked ?? {};
  const lockText =
    locked.update || locked.write
      ? fill(copy.q_lockBusy, {
          who: [
            locked.update
              ? fill(copy.q_lockUpdate, { pid: locked.update })
              : "",
            locked.write ? fill(copy.q_lockWrite, { pid: locked.write }) : "",
          ]
            .filter(Boolean)
            .join(" / "),
        })
      : copy.q_lockFree;
  const est = estimated ? copy.q_estimated : "";
  const delta = (pair?: [Num, Num]) =>
    !pair || !isNum(pair[0]) || !isNum(pair[1])
      ? DASH
      : pair[0] === pair[1]
        ? fill(copy.q_unchangedPct, { v: pair[1] })
        : `${pair[0]}% → **${pair[1]}%**`;
  const chg = mon.chg ?? {};
  const todaySigs = arr(mon.today?.sigs);
  const monNote = fill(copy.q_monNote, {
    step: delta(chg.step),
    mic: delta(chg.mic),
    state: chg.state
      ? chg.state[0] === chg.state[1]
        ? copy.q_unchanged
        : `${chg.state[0]} → **${chg.state[1]}**`
      : DASH,
    sigs: todaySigs.length ? `**${todaySigs.join(" · ")}**` : copy.q_noSig,
    n: mon.hist.length,
    total: nv(mon.tdN),
  });
  // Statuses, never red or green (docs/charts.md); the chart bands and the
  // state tags use the same tones.
  const toneColor = (state: string) =>
    ({
      info: v.cyan,
      danger: v.purple,
      warning: v.orange,
      success: v.primary,
      neutral: v.textMuted,
    })[stateTone(state)];

  // ---- daily state table ----
  const rowsAsc = useMemo(
    () => histRows(mon.hist, onlyChanges),
    [mon.hist, onlyChanges],
  );
  const histData = useMemo(() => [...rowsAsc].reverse(), [rowsAsc]);
  const dash = (x: Num, render: (n: number) => string) =>
    isNum(x) ? render(x) : DASH;
  const histColumns: TableColumnsType<HistRow> = [
    {
      title: copy.q_colDate,
      dataIndex: "date",
      width: 92,
      render: (date: string) =>
        date === d.asof ? (
          <b>
            {date.slice(5)}{" "}
            <span title={copy.q_latestMark} aria-label={copy.q_latestMark}>
              ◀
            </span>
          </b>
        ) : (
          date.slice(5)
        ),
    },
    {
      title: copy.q_colState,
      dataIndex: "state",
      render: (state: string) => (
        <span style={{ color: toneColor(state) }}>{state}</span>
      ),
    },
    {
      title: copy.q_colBreadth,
      dataIndex: "breadth",
      align: "right",
      render: (x: Num) => dash(x, (n) => n.toFixed(1)),
    },
    {
      title: <span title={copy.q_colBqTip}>{copy.q_colBq}</span>,
      dataIndex: "bq",
      align: "right",
      render: (x: Num) => dash(x, (n) => `${n.toFixed(0)}%`),
    },
    {
      title: copy.q_colNdr,
      dataIndex: "ndr",
      align: "right",
      render: (x: Num) => <Signed value={x} digits={1} />,
    },
    {
      title: copy.q_colStep,
      dataIndex: "step",
      align: "right",
      render: (x: Num, row) =>
        isNum(x) ? (
          <>
            {x}%
            {row.stepDir !== 0 && (
              <span
                className="mm-arrow"
                style={{ color: row.stepDir > 0 ? v.up : v.down }}
              >
                {row.stepDir > 0 ? " ▲" : " ▼"}
              </span>
            )}
          </>
        ) : (
          DASH
        ),
    },
    {
      title: copy.q_colMic,
      dataIndex: "mic",
      align: "right",
      render: (x: Num) => dash(x, (n) => `${n}%`),
    },
    {
      title: copy.q_colSigs,
      dataIndex: "sigs",
      render: (x: string) => x || DASH,
    },
  ];
  const runColumns: TableColumnsType<NonNullable<typeof mon.runs>[number]> = [
    { title: copy.q_colAt, dataIndex: "at", width: 118 },
    {
      title: copy.q_colResult,
      dataIndex: "status",
      width: 90,
      render: (s: string) => (
        <span style={{ color: s === "ok" ? v.primary : v.alert }}>
          {runLabel(s)}
        </span>
      ),
    },
    { title: copy.q_colNote, dataIndex: "note" },
  ];

  // ---- charts ----
  const xAxis = (data: string[], boundaryGap = false) => ({
    type: "category",
    data,
    boundaryGap,
    axisLabel: { hideOverlap: true },
  });
  const legend = { top: 0, type: "scroll" };
  const noAnim = { animation: false };
  // Markers follow the terminal habit (docs/charts.md): direction follows
  // meaning. Every bearish signal is a green ▼ (M1-M4 cap the position, the
  // micro-cap overheat stops adding, the outflow is an outflow); the bullish V
  // is a red ▲. Bearish types are told apart by fill (the caps that only warn,
  // M1/M2 and the overheat, are hollow; M3/M4 and the outflow are solid) and
  // by a small label; the legend and tooltip name each one.
  type SigStyle = {
    color: string;
    symbol: string;
    rot: number;
    hollow: boolean;
    tag: string;
    size: number;
  };
  const BULL = { color: v.up, symbol: "triangle", rot: 0, hollow: false };
  // A drawn ▼, not a rotated triangle: the legend ignores symbol rotation and
  // would show a bearish signal as ▲.
  const BEAR = { color: v.down, symbol: "path://M0,0 L10,0 L5,9 Z", rot: 0 };
  const SIG_STYLE: Record<string, SigStyle> = {
    "M1 过热": { ...BEAR, hollow: true, tag: "M1", size: 14 },
    "M2 背离": { ...BEAR, hollow: true, tag: "M2", size: 9 },
    "M3 破位": { ...BEAR, hollow: false, tag: "M3", size: 11 },
    "M4 二波失败": { ...BEAR, hollow: false, tag: "M4", size: 15 },
    "V 底部确认": { ...BULL, tag: "V", size: 13 },
    微盘过热: { ...BEAR, hollow: true, tag: copy.q_tagOver, size: 13 },
    资金退潮: { ...BEAR, hollow: false, tag: copy.q_tagOut, size: 12 },
  };
  const markOf = (name: string) => {
    const st = SIG_STYLE[name];
    return st
      ? { color: st.color, glyph: st.color === v.down ? "▼" : "▲" }
      : undefined;
  };
  const SIG_COLOR: Record<string, string> = Object.fromEntries(
    Object.entries(SIG_STYLE).map(([k, x]) => [k, x.color]),
  );
  const sigColor = (name: string, fallback: string) =>
    SIG_COLOR[name] ?? fallback;
  const stateColor = toneColor;
  const scatterOf = (list: SignalSeries[], yAxisIndex?: number) =>
    arr(list).map((s) => {
      const st = SIG_STYLE[s.name];
      const color = sigColor(s.name, v.textStrong);
      return {
        name: s.name,
        type: "scatter",
        ...(yAxisIndex === undefined ? {} : { yAxisIndex }),
        data: s.pts,
        symbol: st?.symbol ?? s.sym,
        symbolRotate: st?.rot ?? s.rot,
        // Sizes differ so two signals on one day stay visible (M2 nests in M1).
        symbolSize: st?.size ?? 12,
        // Smaller markers on top, so a same-day pair stays visible.
        z: 30 - (st?.size ?? 12),
        labelLayout: { hideOverlap: true },
        itemStyle: st?.hollow
          ? { color: v.surface, borderColor: color, borderWidth: 2 }
          : { color, borderColor: v.surface, borderWidth: 1 },
        emphasis: { scale: 1.5 },
        label: st
          ? {
              show: true,
              formatter: st.tag,
              position: st.color === v.down ? "top" : "bottom",
              fontSize: 9,
              color: v.text,
            }
          : { show: false },
      };
    });

  const mainOption = useMemo(
    () => ({
      ...noAnim,
      grid: { left: 52, right: 56, top: 42, bottom: 36 },
      tooltip: {
        trigger: "axis",
        formatter: (params: Parameters<typeof mainTooltip>[2]) =>
          mainTooltip(
            copy,
            d.dayinfo,
            Array.isArray(params) ? params : [params],
            markOf,
          ),
      },
      legend,
      xAxis: xAxis(d.dmain),
      yAxis: [
        { type: "value", scale: true, name: copy.q_axisIndex },
        { type: "value", min: 0, max: 100, splitLine: { show: false } },
      ],
      series: [
        {
          name: copy.q_sLead,
          type: "line",
          data: d.lead,
          symbol: "none",
          lineStyle: { width: 2, color: v.primary },
          itemStyle: { color: v.primary },
          areaStyle: { color: v.primary, opacity: 0.06 },
        },
        {
          name: copy.q_sDef,
          type: "line",
          data: d.def,
          symbol: "none",
          lineStyle: { width: 1.8, color: v.orange },
          itemStyle: { color: v.orange },
        },
        {
          name: copy.q_sBreadth,
          type: "line",
          yAxisIndex: 1,
          data: d.breadth,
          symbol: "none",
          lineStyle: { width: 1.2, color: v.cyan, type: "dashed" },
          itemStyle: { color: v.cyan },
          // State bands sit in the empty 0-3 range of the breadth axis.
          markArea: {
            silent: true,
            tooltip: { show: false },
            data: arr(d.stband).map((a) => [
              {
                xAxis: a.x0,
                yAxis: 0,
                itemStyle: { color: stateColor(a.st), opacity: 0.35 },
              },
              { xAxis: a.x1, yAxis: 3 },
            ]),
          },
        },
        {
          name: copy.q_sSwitch,
          type: "scatter",
          yAxisIndex: 1,
          // Neutral: a gray tick, not a coloured triangle.
          symbol: "rect",
          symbolSize: [2, 10],
          z: 11,
          itemStyle: { color: v.textMuted },
          data: arr(d.stmark).map((m) => ({
            value: [m.d, 3.6, m.st],
            itemStyle: {
              color: v.textMuted,
              borderColor: v.surface,
              borderWidth: 1,
            },
          })),
          emphasis: { scale: 1.5 },
          label: { show: false },
        },
        ...scatterOf(d.sigs),
      ],
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [d, v, copy],
  );
  const breadthOption = useMemo(
    () => ({
      ...noAnim,
      grid: { left: 52, right: 56, top: 36, bottom: 36 },
      tooltip: { trigger: "axis" },
      legend,
      xAxis: xAxis(d.dbr),
      yAxis: [
        { type: "value", min: 0, max: 100 },
        { type: "value", min: -100, max: 40, splitLine: { show: false } },
      ],
      series: [
        {
          name: copy.q_ndr,
          type: "bar",
          yAxisIndex: 1,
          // NDR is signed: red above zero, green below; secondary, so light.
          data: arr(d.ndr2).map((x) => ({
            value: x,
            itemStyle: { color: v.sign(x) ?? v.textMuted, opacity: 0.5 },
          })),
          itemStyle: { color: v.textMuted, opacity: 0.5 },
        },
        {
          name: copy.q_breadth,
          type: "line",
          data: d.breadth2,
          symbol: "none",
          lineStyle: { width: 2, color: v.primary },
          itemStyle: { color: v.primary },
          markLine: {
            silent: true,
            symbol: "none",
            label: { color: v.text, fontSize: 10, formatter: "20%" },
            lineStyle: v.threshold,
            data: [{ yAxis: 20 }],
          },
        },
      ],
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [d, v, copy],
  );
  const basketOption = useMemo(
    () => ({
      ...noAnim,
      grid: { left: 52, right: 56, top: 36, bottom: 36 },
      tooltip: { trigger: "axis" },
      legend,
      xAxis: xAxis(d.dmain),
      yAxis: [
        { type: "value", min: 0, max: 100 },
        { type: "value", scale: true, splitLine: { show: false } },
      ],
      series: [
        {
          name: ">MA20",
          type: "line",
          data: d.bA20,
          symbol: "none",
          lineStyle: { width: 1, color: v.ma[20] },
          itemStyle: { color: v.ma[20] },
        },
        {
          name: ">MA60",
          type: "line",
          data: d.bA60,
          symbol: "none",
          lineStyle: { width: 1, color: v.ma[60] },
          itemStyle: { color: v.ma[60] },
        },
        {
          name: ">MA200",
          type: "line",
          data: d.bA200,
          symbol: "none",
          lineStyle: { width: 1, color: v.ma[200] },
          itemStyle: { color: v.ma[200] },
        },
        {
          name: copy.q_sBasketIdx,
          type: "line",
          yAxisIndex: 1,
          data: d.leadX,
          symbol: "none",
          lineStyle: { width: 2, color: v.primary },
          itemStyle: { color: v.primary },
        },
      ],
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [d, v, copy],
  );
  const ladderOption = (
    dates: string[],
    step: { eq: Num[]; hold: Num[]; posa: Num[] },
  ) => ({
    ...noAnim,
    grid: { left: 50, right: 56, top: 36, bottom: 36 },
    tooltip: {
      trigger: "axis",
      formatter: (params: Parameters<typeof seriesTooltip>[1]) =>
        seriesTooltip(
          copy,
          Array.isArray(params) ? params : [params],
          [copy.q_sPos],
          markOf,
        ),
    },
    legend,
    xAxis: xAxis(dates, true),
    yAxis: [
      { type: "value", min: 0, max: 100, splitLine: { show: false } },
      { type: "value", scale: true },
    ],
    series: [
      {
        name: copy.q_sPos,
        type: "line",
        step: "end",
        data: step.posa,
        symbol: "none",
        lineStyle: { width: 1, color: v.cyan },
        itemStyle: { color: v.cyan },
        areaStyle: { color: v.cyan, opacity: 0.18 },
        z: 1,
      },
      {
        name: copy.q_sEq,
        type: "line",
        yAxisIndex: 1,
        data: rebase(step.eq),
        symbol: "none",
        lineStyle: { width: 2, color: v.primary },
        itemStyle: { color: v.primary },
        z: 5,
      },
      {
        name: copy.q_sHold,
        type: "line",
        yAxisIndex: 1,
        data: rebase(step.hold),
        symbol: "none",
        lineStyle: { width: 1.4, color: v.textMuted, type: "dashed" },
        itemStyle: { color: v.textMuted },
      },
    ],
  });
  const stepOption = useMemo(
    () => ladderOption(d.dmain, S),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [d, v, copy],
  );
  const mstepOption = useMemo(
    () => ladderOption(d.dmw, MS),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [d, v, copy],
  );
  const microOption = useMemo(
    () => ({
      ...noAnim,
      grid: { left: 52, right: 56, top: 42, bottom: 36 },
      tooltip: {
        trigger: "axis",
        formatter: (params: Parameters<typeof seriesTooltip>[1]) =>
          seriesTooltip(
            copy,
            Array.isArray(params) ? params : [params],
            [],
            markOf,
          ),
      },
      legend,
      xAxis: xAxis(d.dmw),
      yAxis: [
        { type: "value", scale: true, name: copy.q_axisIndex },
        { type: "value", min: 0, max: 100, splitLine: { show: false } },
      ],
      series: [
        {
          name: copy.q_sMic,
          type: "line",
          data: d.mic,
          symbol: "none",
          lineStyle: { width: 2, color: v.primary },
          itemStyle: { color: v.primary },
          areaStyle: { color: v.primary, opacity: 0.05 },
          markArea: {
            silent: true,
            itemStyle: { color: v.cyan, opacity: 0.14 },
            label: { show: false },
            data: arr(d.mareas),
          },
        },
        {
          name: copy.q_sMew,
          type: "line",
          data: d.mew,
          symbol: "none",
          lineStyle: { width: 1.4, color: v.series[4] },
          itemStyle: { color: v.series[4] },
        },
        {
          name: copy.q_sMbw,
          type: "line",
          yAxisIndex: 1,
          data: d.mbw,
          symbol: "none",
          lineStyle: { width: 1.2, color: v.purple, type: "dashed" },
          itemStyle: { color: v.purple },
        },
        ...scatterOf(d.msigs),
      ],
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [d, v, copy],
  );
  const flowOption = useMemo(
    () => ({
      ...noAnim,
      grid: { left: 52, right: 56, top: 42, bottom: 36 },
      tooltip: {
        trigger: "axis",
        formatter: (params: Parameters<typeof seriesTooltip>[1]) =>
          seriesTooltip(
            copy,
            Array.isArray(params) ? params : [params],
            [copy.q_sMshare],
            markOf,
          ),
      },
      legend,
      xAxis: xAxis(d.dmw, true),
      yAxis: [
        { type: "value", scale: true, name: copy.q_axisRs },
        {
          type: "value",
          scale: true,
          name: copy.q_axisShare,
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: copy.q_sMshare,
          type: "bar",
          yAxisIndex: 1,
          data: d.msh,
          itemStyle: { color: v.cyan, opacity: 0.55 },
        },
        {
          name: copy.q_sMrs,
          type: "line",
          data: d.mrsn,
          symbol: "none",
          lineStyle: { width: 1.8, color: v.primary },
          itemStyle: { color: v.primary },
        },
        ...scatterOf(d.mfsigs, 1),
      ],
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [d, v, copy],
  );

  const chart = (
    label: string,
    option: ChartOption,
    height: number,
    has: boolean,
  ) =>
    has ? (
      <EChart label={label} option={option} height={height} />
    ) : (
      <Empty description={copy.noData} />
    );

  // ---- ladder v4 ----
  const G = [0, 1, 2, 3].map((i) => ({
    key: String(i),
    title: copyText(copy, `q_g${i}n`),
    value: ["0%", "25%", "50%", "100%"][i],
    desc: i === S.stage ? copy.q_curTier : copyText(copy, `q_g${i}c`),
  }));
  const capWhy = (() => {
    const key = `q_why_${S.capr}`;
    return Object.hasOwn(copy, key) ? copyText(copy, key) : S.capr;
  })();
  const stepNext = S.cap
    ? fill(copy.q_stCapped, { why: capWhy, pos: S.pos })
    : fill(copyText(copy, `q_stNext${Math.min(Math.max(S.stage, 0), 3)}`), {
        bq: nv(S.bq),
        rep: sx(S.rep),
        band: S.band,
        px60: sx(S.px60),
        hold: nv(S.holdN),
      });
  const stepNote = fill(copy.q_stNow, {
    tier: G[S.stage]?.title ?? DASH,
    pos: S.pos,
    next: stepNext,
    sw: nv(S.diag.sw),
    med: nv(S.diag.med),
    short: nv(S.diag.short),
  });

  // ---- micro ladder ----
  const need = (MS.ma200 * (1 + MS.up / 100)) / MS.px - 1;
  const deepOn = d.deepNow && !!d.deepSeg;
  const mstepNote = fill(copy.q_msNote, {
    deep: d.deepNow
      ? fill(copy.q_msDeepYes, { n: nv(d.deepDays) })
      : copy.q_msDeepNo,
    bear: MS.bear ? copy.q_msBear : copy.q_msBull,
    sw: nv(MS.diag.sw),
    med: nv(MS.diag.med),
    short: nv(MS.diag.short),
  });
  const ds = d.deepst;
  const deepNote = deepOn
    ? fill(copy.q_deepNow, {
        from: d.deepSeg![0],
        days: nv(d.deepDays),
        asof: d.asof,
      })
    : copy.q_deepNot;
  const msigNote = fill(copy.q_msigNote, {
    n: nv(ds.n),
    med60: sx(ds.med60),
    win60: nv(ds.win60),
    n60: nv(ds.n60),
    med120: sx(ds.med120),
    win120: nv(ds.win120),
    start: ds.lastStart ?? DASH,
    len: nv(ds.lastLen),
    now: d.deepNow ? copy.q_deepContinues : copy.q_deepEnded,
  });

  // ---- tables ----
  const logTable = (rows: [string, string, string][]) => (
    <Table
      size="small"
      pagination={false}
      rowKey={(r) => r.join("|")}
      dataSource={arr(rows)}
      locale={{ emptyText: copy.q_noSigTable }}
      scroll={{ x: 520 }}
      columns={[
        { title: copy.q_colTrigger, dataIndex: 0, width: 110 },
        { title: copy.q_colSignal, dataIndex: 1, width: 150 },
        { title: copy.q_colMeaning, dataIndex: 2 },
      ]}
    />
  );
  const base = d.base ?? {};
  const baseRows = Object.entries(base).map(([name, b]) => ({ name, ...b }));
  const signColor = (x: Num) =>
    isNum(x) ? (x > 0 ? v.up : x < 0 ? v.down : undefined) : undefined;
  type BaseRow = (typeof baseRows)[number];
  const numCell = (
    title: string,
    field: keyof BaseRow,
    render: (r: BaseRow) => ReactNode,
  ) => ({
    title,
    dataIndex: field as string,
    align: "right" as const,
    onCell: (r: BaseRow) => ({ colSpan: r.n ? 1 : field === "win" ? 5 : 0 }),
    render: (_: unknown, r: BaseRow) =>
      r.n ? render(r) : field === "win" ? copy.q_baseNoSample : null,
  });
  const baseColumns: TableColumnsType<BaseRow> = [
    { title: copy.q_colSignal, dataIndex: "name" },
    { title: copy.q_colN, dataIndex: "n", align: "right" },
    numCell(copy.q_colWin60, "win", (r) => `${nv(r.win)}%`),
    numCell(copy.q_colMed60, "med", (r) => (
      <span style={{ color: signColor(r.med) }}>{sg(r.med)}%</span>
    )),
    numCell(copy.q_colExc, "exc", (r) =>
      isNum(r.exc) ? (
        <span style={{ color: signColor(r.exc) }}>{sg(r.exc)}%</span>
      ) : (
        DASH
      ),
    ),
    numCell(copy.q_colDd10, "dd10", (r) => `${nv(r.dd10)}%`),
    numCell(copy.q_colMedDd, "meddd", (r) => (
      <span style={{ color: v.down }}>{nv(r.meddd)}%</span>
    )),
  ];
  const vs = d.vstat;
  const baseNote = fill(copy.q_baseNote, {
    n2: nv(base["M2 背离"]?.n),
    nv: nv(base["V 底部确认"]?.n),
    vall: nv(vs.all.n),
    vout: nv(vs.out.n),
    vwin: nv(vs.out.win),
    n3: nv(base["M3 破位"]?.n),
    n4: nv(base["M4 二波失败"]?.n),
  });

  // ---- methodology numbers ----
  const st = S.stat;
  const ms = MS.stat;
  const f = d.flowstat;
  const mv: Record<string, string> = {
    delisted: nv(d.delisted?.used),
    spV: fill(copy.q_spV, {
      n: nv(vs.all.n),
      med: sx(vs.all.med),
      win: nv(vs.all.win),
      on: nv(vs.out.n),
      ow: nv(vs.out.win),
    }),
    spFlow: fill(copy.q_spFlow, {
      n: nv(f.n),
      med: sx(f.med),
      win: nv(f.win),
    }),
    spDeep: fill(copy.q_spDeep, {
      n: nv(ds.n),
      med60: sx(ds.med60),
      win60: nv(ds.win60),
      n60: nv(ds.n60),
      med120: sx(ds.med120),
      win120: nv(ds.win120),
    }),
    hold1: sx(st.hold.cagr),
    hold2: sx(st.hold.dd),
    hold3: nv(st.hold.calmar),
    hold4: sx(st.y26h.ret),
    st1: sx(st.all.cagr),
    st2: sx(st.all.dd),
    st3: nv(st.all.calmar),
    st4: sx(st.y26.ret),
    out1: sx(st.out.cagr),
    out2: sx(st.out.dd),
    out3: nv(st.out.calmar),
    mh1: sx(ms.hold.cagr),
    mh2: sx(ms.hold.dd),
    mh3: nv(ms.hold.calmar),
    mh4: sx(ms.y24H.ret),
    mh5: sx(ms.y26H.ret),
    ms1: sx(ms.all.cagr),
    ms2: sx(ms.all.dd),
    ms3: nv(ms.all.calmar),
    ms4: sx(ms.y24.ret),
    ms5: sx(ms.y26.ret),
    mo1: sx(ms.out.cagr),
    mo2: sx(ms.out.dd),
    mo3: nv(ms.out.calmar),
    mo4: `${sx(ms.outH.cagr)}${copy.q_perYear} · Calmar ${nv(ms.outH.calmar)}`,
  };
  void locale;

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      <div className="mm-quant-meta">
        <span className="mm-muted">{copy.q_sub}</span>
        <Space wrap size={[16, 4]}>
          <span className="mm-muted">
            {copy.q_asof} <b>{d.asof}</b>
          </span>
          {d.gen && (
            <span className="mm-muted">
              {copy.q_gen} {d.gen}
            </span>
          )}
          <span className="mm-muted">{copy.q_source}</span>
          <span className="mm-muted">
            {copy.q_daily}{" "}
            <b style={{ color: lagColor }} data-testid="quant-lag">
              {lagText}
            </b>
          </span>
        </Space>
      </div>
      <Panels>
        <Panel
          title={copy.q_leadTitle}
          extra={<span className="mm-muted">{copy.q_leadHint}</span>}
        >
          <Space orientation="vertical" size={12} style={{ width: "100%" }}>
            {stateCard(d.state, d.stateCode, leadNear, copy.q_leadTitle)}
            <KpiRow items={leadItems} cols={kpiCols} />
          </Space>
        </Panel>
        <Panel
          title={copy.q_microTitle}
          extra={<span className="mm-muted">{copy.q_microHint}</span>}
        >
          <Space orientation="vertical" size={12} style={{ width: "100%" }}>
            {stateCard(d.mstate, d.mcode, microNear, copy.q_microTitle)}
            <KpiRow items={microItems} cols={kpiCols} />
          </Space>
        </Panel>
        <Panel kind="wide" title={copy.q_fsmTitle}>
          <Hint>{copy.q_fsmHint}</Hint>
          <StepStrip
            steps={fsmSteps}
            active={fsmIndex(d.state)}
            pastBefore={5}
            label={copy.q_fsmTitle}
          />
        </Panel>
        <Panel kind="wide" title={copy.q_monTitle}>
          <Hint>{copy.q_monHint}</Hint>
          <div className="mm-gates">
            <Gate
              tone={lag === 0 ? "out" : lagWarn ? "" : "hit"}
              title={fill(copy.q_g1, { est })}
              value={
                lag === 0
                  ? copy.q_g1Ok
                  : !isNum(lag)
                    ? copy.q_g1None
                    : fill(copy.q_g1Behind, { n: lag })
              }
            >
              {fill(copy.q_g1Detail, {
                asof: d.asof,
                expect: mon.expect || DASH,
                diff: isNum(lag) ? fill(copy.q_g1Diff, { n: lag }) : "",
                est: estimated ? copy.q_g1Est : "",
              })}
            </Gate>
            <Gate
              tone={Math.abs(mon.cover) < 5 ? "" : "hit"}
              title={copy.q_g2}
              value={fill(copy.q_g2Value, {
                n: mon.days.toLocaleString(locale),
              })}
            >
              {fill(copy.q_g2Detail, {
                prev: mon.prevDays.toLocaleString(locale),
                chg: `${mon.cover > 0 ? "+" : ""}${mon.cover}`,
              })}
            </Gate>
            <Gate
              tone={runOk === false ? "hit" : runOk ? "out" : ""}
              title={copy.q_g3}
              value={run ? (runOk ? copy.q_g3Ok : copy.q_g3Bad) : copy.q_g3None}
            >
              {run
                ? `${run.date ?? ""} ${run.at ?? ""} · ${runLabel(run.status)}`
                : copy.q_g3NoneDetail}
              {" · "}
              {lockText}
            </Gate>
          </div>
          <div className="mm-note">{rich(monNote)}</div>
          <div className="mm-note">
            <b>{copy.q_runsTitle}</b>{" "}
            <span className="mm-muted">{copy.q_runsHint}</span>
          </div>
          {arr(mon.runs).length ? (
            <Table
              size="small"
              pagination={false}
              rowKey={(r) => `${r.date}|${r.at}`}
              dataSource={arr(mon.runs)}
              columns={runColumns}
              scroll={{ x: 480 }}
            />
          ) : (
            <div className="mm-muted">{copy.q_runsNone}</div>
          )}
        </Panel>
        <Panel kind="wide" title={copy.q_mainTitle}>
          <Hint>{copy.q_mainHint}</Hint>
          {chart(copy.q_mainTitle, mainOption, 400, arr(d.dmain).length > 0)}
        </Panel>
        <Panel title={copy.q_brTitle}>
          <Hint>{copy.q_brHint}</Hint>
          {chart(copy.q_brTitle, breadthOption, 300, arr(d.dbr).length > 0)}
        </Panel>
        <Panel title={copy.q_bkTitle}>
          <Hint>{copy.q_bkHint}</Hint>
          {chart(copy.q_bkTitle, basketOption, 300, arr(d.dmain).length > 0)}
        </Panel>
        <Panel kind="wide" title={copy.q_stTitle}>
          <Hint>{copy.q_stHint}</Hint>
          <StepStrip
            steps={G}
            active={S.stage}
            pastBefore={0}
            label={copy.q_sPos}
          />
          <div className="mm-note">{rich(stepNote)}</div>
          <div className="mm-muted">
            {rich(statLine(copy, "q_stStat", st.all, st.hold, st.y26, st.y26h))}
          </div>
          {chart(copy.q_stTitle, stepOption, 320, arr(d.dmain).length > 0)}
        </Panel>
        <Panel kind="wide" title={copy.q_micTitle}>
          <Hint>{copy.q_micHint}</Hint>
          <div className="mm-note">{rich(deepNote)}</div>
          {chart(copy.q_micTitle, microOption, 380, arr(d.dmw).length > 0)}
        </Panel>
        <Panel kind="wide" title={copy.q_flowTitle}>
          <Hint>{copy.q_flowHint}</Hint>
          {chart(copy.q_flowTitle, flowOption, 320, arr(d.dmw).length > 0)}
        </Panel>
        <Panel kind="wide" title={copy.q_msTitle}>
          <Hint>{copy.q_msHint}</Hint>
          <div className="mm-gates">
            <Gate
              tone={MS.bear ? "hit" : ""}
              title={copy.q_mg1}
              value={MS.bear ? copy.q_mg1Bear : copy.q_mg1Bull}
            >
              {rich(
                fill(copy.q_mg1Detail, {
                  px: nv(MS.px),
                  ma: nv(MS.ma200),
                  d: sx(MS.dma200),
                  below: MS.bear
                    ? fill(copy.q_mg1Below, { n: nv(MS.belowDays) })
                    : "",
                  up: MS.up,
                }),
              )}
            </Gate>
            <Gate
              tone={MS.over ? "hit" : ""}
              title={copy.q_mg2}
              value={MS.over ? copy.q_mg2On : copy.q_mg2Off}
            >
              {rich(fill(copy.q_mg2Detail, { b: nv(d.mb), d: sx(d.md60) }))}
            </Gate>
            <Gate tone="out" title={copy.q_mg3} value={`${MS.pos}%`}>
              {(MS.bear
                ? fill(copy.q_mg3Bear, {
                    up: MS.up,
                    need: (need * 100).toFixed(1),
                  })
                : copy.q_mg3Bull) + fill(copy.q_mg3Hold, { n: nv(MS.holdN) })}
            </Gate>
          </div>
          <div className="mm-note">{rich(mstepNote)}</div>
          <div className="mm-muted">
            {rich(statLine(copy, "q_msStat", ms.all, ms.hold, ms.y26, ms.y26H))}
          </div>
          {chart(copy.q_msTitle, mstepOption, 320, arr(d.dmw).length > 0)}
        </Panel>
        <Panel kind="detail" title={copy.q_histTitle}>
          <div className="mm-between mm-hist-filter">
            <Checkbox
              checked={onlyChanges}
              onChange={(e) => {
                setOnlyChanges(e.target.checked);
                setPage(1);
              }}
            >
              {copy.q_histOnlyChg}
            </Checkbox>
            <span className="mm-muted" data-testid="hist-count">
              {fill(copy.q_histCount, {
                shown: rowsAsc.length,
                total: mon.hist.length,
              })}
            </span>
          </div>
          <Table<HistRow>
            size="small"
            rowKey="date"
            dataSource={histData}
            columns={histColumns}
            scroll={{ x: 720 }}
            rowClassName={(r) => (r.date === d.asof ? "mm-today" : "")}
            pagination={{
              current: page,
              pageSize: PAGE_SIZE,
              showSizeChanger: false,
              hideOnSinglePage: true,
              onChange: setPage,
            }}
          />
        </Panel>
        <Panel kind="detail" title={copy.q_sigTitle}>
          <Hint>{copy.q_sigHint}</Hint>
          {logTable(d.sig)}
        </Panel>
        <Panel kind="detail" title={copy.q_msigTitle}>
          <Hint>{copy.q_msigHint}</Hint>
          <div className="mm-note">{rich(msigNote)}</div>
          {logTable(d.msig)}
        </Panel>
        <Panel kind="detail" title={copy.q_baseTitle}>
          <Hint>{copy.q_baseHint}</Hint>
          <div className="mm-note">{rich(baseNote)}</div>
          <Table<BaseRow>
            size="small"
            pagination={false}
            rowKey="name"
            dataSource={baseRows}
            columns={baseColumns}
            scroll={{ x: 640 }}
          />
        </Panel>
      </Panels>
      <Collapse
        className="mm-method"
        destroyOnHidden
        items={[
          {
            key: "method",
            label: copy.q_methodTitle,
            children: (
              <>
                <QuantMethod vars={mv} />
                <div className="mm-spec-note mm-why">
                  {rich(copy.q_footNote)}
                </div>
              </>
            ),
          },
        ]}
      />
    </Space>
  );
}
