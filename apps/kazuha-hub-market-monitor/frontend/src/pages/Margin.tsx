import { useMemo, useState } from "react";
import {
  Alert,
  Descriptions,
  Drawer,
  Empty,
  Progress,
  Segmented,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import type { TableColumnsType } from "antd";
import { ByteSearch } from "../components/ByteSearch";
import { Panel, Panels } from "../components/Panels";
import { Dashboard } from "../components/Dashboard";
import { EChart } from "../components/EChart";
import { KpiRow } from "../components/Kpi";
import { RowTable } from "../components/RowTable";
import { Signed } from "../components/Signed";
import { useVisual, type Visual } from "../components/useVisual";
import { useCopy, type Copy } from "../lib/copy";
import {
  arr,
  fill,
  fmt,
  formatYi,
  isNum,
  signed,
  splitTags,
  DASH,
  type Num,
} from "../lib/format";
import { useRowDetail } from "../lib/hooks";
import { valueLabel, valueOptions } from "../lib/labels";
import {
  MECHANISMS,
  fragTone,
  histBinLabel,
  parseRatioHist,
  ratioHistBars,
} from "../lib/margin";

type MarginSummary = {
  meta?: { assumptions?: { k_call?: Num; k_liq?: Num } };
  hist_dates?: string[];
  overview?: {
    rz_total?: Num;
    rq_total?: Num;
    n_total?: Num;
    n_high?: Num;
    n_watch?: Num;
    ratio_med?: Num;
    ratio_p90?: Num;
    ratio_p99?: Num;
    n_over8?: Num;
    n_over10?: Num;
    n_critical?: Num;
    n_latent?: Num;
    n_flushed?: Num;
    n_pledge?: Num;
    n_pledge_breach?: Num;
    res_hist?: { k: number | string; n: Num }[];
    // Newer snapshots only; validated by parseRatioHist.
    ratio_hist?: unknown;
  };
};

export type MarginRow = {
  code: string;
  name?: string;
  price?: Num;
  chg?: Num;
  ratio?: Num;
  dratio20?: Num;
  pnl?: Num;
  buf_call?: Num;
  buf_liq?: Num;
  score?: Num;
  frag?: Num;
  level?: string;
  state?: string;
  tags?: string;
  rz?: Num;
  rz_chg20?: Num;
  cost?: Num;
  vol_pct?: Num;
  amt_vr?: Num;
  pld_ratio?: Num;
  pld_room?: Num;
  ulk60?: Num;
  ulk_next?: string | null;
  cb_prem?: Num;
  blk_disc?: Num;
  gdhs_chg?: Num;
  fund_pct?: Num;
  res_cnt?: Num;
  res_detail?: string | null;
};
type MarginDetail = { c?: Num[]; r?: Num[] };

// Data values produced by the pipeline and sent to the backend as filters;
// their display text comes from the locale copy (see lib/labels).
const STATES = ["临界", "潜伏", "已去杠杆", "安全"];
const LEVELS = ["高危", "关注", "正常"];
const TAGS = [
  "价跌加杠杆",
  "占比畸高",
  "涨中撤杠杆",
  "杠杆沉淀厚",
  "杠杆定价",
  "高位加杠杆",
];

function stateColor(state: string | undefined): string {
  return (
    (
      {
        // Statuses, not signs (docs/charts.md): never red or green.
        临界: "orange",
        潜伏: "gold",
        已去杠杆: "processing",
        安全: "default",
      } as Record<string, string>
    )[state ?? ""] ?? "default"
  );
}
const levelColor = (level: string | undefined) =>
  (({ 高危: "orange", 关注: "gold" }) as Record<string, string>)[level ?? ""] ??
  "default";

function redIf(cond: boolean, v: Visual, text: string) {
  // A warning highlight, not a sign: strong orange, never red.
  return <span style={cond ? { color: v.alert } : undefined}>{text}</span>;
}

export function MarginPage() {
  const { copy } = useCopy();
  return (
    <Dashboard<MarginSummary> module="margin" title={copy.marginTitle}>
      {(ctx) => <MarginBody {...ctx} />}
    </Dashboard>
  );
}

function MarginBody({
  summary,
  date,
  revision,
}: {
  summary: MarginSummary;
  date: string;
  revision: number;
}) {
  const { copy, locale } = useCopy();
  const v = useVisual();
  const o = summary.overview ?? {};
  const [view, setView] = useState<"lever" | "struct">("lever");
  const [search, setSearch] = useState("");
  const [state, setState] = useState<string>();
  const [level, setLevel] = useState<string>();
  const [tag, setTag] = useState<string>();
  const [mechanism, setMechanism] = useState<string>();
  const [selected, setSelected] = useState<MarginRow | null>(null);
  const filters = useMemo(
    () => ({ state, level, tags: tag }),
    [state, level, tag],
  );

  const kpis = [
    { key: "rz", title: copy.margin_rz, value: formatYi(o.rz_total, locale) },
    { key: "rq", title: copy.margin_rq, value: formatYi(o.rq_total, locale) },
    {
      key: "n",
      title: copy.margin_n,
      value: isNum(o.n_total) ? String(o.n_total) : DASH,
    },
    {
      key: "q",
      title: copy.margin_ratio,
      value: `${fmt(o.ratio_med, 2)}% / ${fmt(o.ratio_p90, 2)}%`,
    },
    {
      key: "hw",
      title: copy.margin_highWatch,
      value: `${o.n_high ?? DASH} / ${o.n_watch ?? DASH}`,
    },
    {
      key: "p",
      title: copy.margin_pledge,
      value: `${o.n_pledge ?? DASH} / ${o.n_pledge_breach ?? DASH}`,
    },
  ];

  const ratioHist = useMemo(() => parseRatioHist(o.ratio_hist), [o.ratio_hist]);
  const histogram = useMemo(() => {
    if (!ratioHist) return null;
    const median = ratioHist.median ?? o.ratio_med;
    return {
      tooltip: {},
      grid: { left: 40, right: 10, top: 20, bottom: 30 },
      xAxis: {
        type: "category",
        data: ratioHistBars(ratioHist).map((b) => b.label),
        name: "%",
      },
      yAxis: { type: "value" },
      series: [
        {
          type: "bar",
          data: ratioHistBars(ratioHist).map((b) => ({
            value: b.value,
            // Bins past the crowding threshold stand out in amber (not red: no sign).
            itemStyle: { color: b.danger ? v.orange : v.primary },
          })),
          markLine: isNum(median)
            ? {
                silent: true,
                symbol: "none",
                data: [
                  {
                    xAxis: histBinLabel(ratioHist, median),
                    label: { formatter: copy.margin_histMedian },
                  },
                ],
              }
            : undefined,
        },
      ],
    };
  }, [ratioHist, o.ratio_med, v, copy]);
  const quantiles = useMemo(
    () => ({
      tooltip: {},
      grid: { left: 44, right: 16, top: 24, bottom: 28 },
      xAxis: { type: "category", data: ["P50", "P90", "P99"] },
      yAxis: { type: "value", name: "%" },
      series: [
        {
          type: "bar",
          data: [o.ratio_med, o.ratio_p90, o.ratio_p99].map((value) => ({
            value: isNum(value) ? value : null,
            itemStyle: {
              color: isNum(value) && value >= 8 ? v.orange : v.primary,
            },
          })),
          label: {
            show: true,
            position: "top",
            formatter: (p: { value: number }) => fmt(p.value, 2),
          },
          markLine: {
            silent: true,
            symbol: "none",
            data: [
              {
                yAxis: 8,
                label: {
                  formatter: "8%",
                  position: "insideEndTop",
                  color: v.text,
                  textBorderWidth: 0,
                },
                lineStyle: v.threshold,
              },
            ],
          },
        },
      ],
    }),
    [o.ratio_med, o.ratio_p90, o.ratio_p99, v],
  );
  const stateOption = useMemo(() => {
    const stateCounts = [
      ["临界", o.n_critical],
      ["潜伏", o.n_latent],
      ["已去杠杆", o.n_flushed],
    ] as const;
    const safe = isNum(o.n_total)
      ? o.n_total -
        stateCounts.reduce((sum, [, n]) => sum + (isNum(n) ? n : 0), 0)
      : null;
    return {
      tooltip: { trigger: "item" },
      legend: { bottom: 0 },
      series: [
        {
          type: "pie",
          radius: ["45%", "70%"],
          center: ["50%", "45%"],
          label: { formatter: "{b}\n{c}" },
          data: [...stateCounts, ["安全", safe] as const]
            .filter(([, n]) => isNum(n))
            .map(([key, value]) => ({
              name: valueLabel(copy, key),
              value,
              itemStyle: {
                color: {
                  临界: v.alert,
                  潜伏: v.orange,
                  已去杠杆: v.primary,
                  安全: v.series[4],
                }[key],
              },
            })),
        },
      ],
    };
  }, [o.n_critical, o.n_latent, o.n_flushed, o.n_total, v, copy]);
  const resHist = useMemo(() => arr(o.res_hist), [o.res_hist]);
  const resOption = useMemo(
    () => ({
      tooltip: {},
      grid: { left: 40, right: 10, top: 20, bottom: 28 },
      xAxis: { type: "category", data: resHist.map((h) => String(h.k)) },
      yAxis: { type: "value" },
      series: [
        {
          type: "bar",
          data: resHist.map((h) => h.n ?? null),
          itemStyle: { color: v.primary },
          label: { show: true, position: "top" },
        },
      ],
    }),
    [resHist, v],
  );

  const num = (
    title: string,
    field: string,
    render: (value: Num, row: MarginRow) => React.ReactNode,
    width = 90,
  ) => ({
    title,
    dataIndex: field,
    align: "right" as const,
    width,
    sorter: true,
    render,
  });
  const base: TableColumnsType<MarginRow> = [
    { title: copy.col_code, dataIndex: "code", width: 84, fixed: "left" },
    { title: copy.col_name, dataIndex: "name", width: 96, fixed: "left" },
    {
      title: copy.col_price,
      dataIndex: "price",
      align: "right",
      width: 72,
      render: (x: Num) => fmt(x, 2),
    },
    {
      title: copy.col_chg,
      dataIndex: "chg",
      align: "right",
      width: 80,
      sorter: true,
      render: (x: Num) => (
        <span
          style={{
            color: !isNum(x) || x === 0 ? undefined : x > 0 ? v.up : v.down,
          }}
        >
          {signed(x, 2)}
        </span>
      ),
    },
  ];
  const lever: TableColumnsType<MarginRow> = [
    num(copy.col_ratio, "ratio", (x) => fmt(x, 2), 96),
    num(
      copy.col_dratio20,
      "dratio20",
      (x) => <Signed value={x} digits={2} suffix="pp" />,
      110,
    ),
    num(
      copy.col_pnl,
      "pnl",
      (x) => <Signed value={x} digits={1} suffix="%" />,
      88,
    ),
    num(
      copy.col_bufCall,
      "buf_call",
      (x) => redIf(isNum(x) && x < 15, v, isNum(x) ? `${fmt(x, 1)}%` : DASH),
      100,
    ),
    num(copy.col_score, "score", (x) => fmt(x, 0), 100),
    num(
      copy.col_frag,
      "frag",
      (x) =>
        isNum(x) ? (
          <Progress
            percent={Math.round(x)}
            size="small"
            // A 0-100 score, not a percentage; 100 is the most fragile value,
            // not a success, so keep the number and never the check mark.
            status="normal"
            format={(p) => `${p}`}
            aria-label={copy.col_frag}
            strokeColor={fragTone(x) ? v[fragTone(x)!] : undefined}
          />
        ) : (
          DASH
        ),
      124,
    ),
  ];
  const struct: TableColumnsType<MarginRow> = [
    num(
      copy.col_pldRatio,
      "pld_ratio",
      (x) => (isNum(x) ? `${fmt(x, 1)}%` : DASH),
      96,
    ),
    num(
      copy.col_pldRoom,
      "pld_room",
      (x) => redIf(isNum(x) && x < 15, v, isNum(x) ? `${fmt(x, 1)}%` : DASH),
      116,
    ),
    num(copy.col_ulk60, "ulk60", (x) => (x ? `${fmt(x, 2)}%` : DASH), 92),
    num(
      copy.col_cbPrem,
      "cb_prem",
      (x) => redIf(isNum(x) && x < 0, v, isNum(x) ? `${fmt(x, 1)}%` : DASH),
      96,
    ),
    num(
      copy.col_gdhsChg,
      "gdhs_chg",
      (x) => <Signed value={x} digits={1} suffix="%" />,
      96,
    ),
    num(
      copy.col_fundPct,
      "fund_pct",
      (x) => (isNum(x) ? `${fmt(x, 2)}%` : DASH),
      96,
    ),
    num(
      copy.col_resCnt,
      "res_cnt",
      (x) =>
        isNum(x) && x >= 2 ? <Tag color="orange">{x}</Tag> : x ? x : DASH,
      80,
    ),
  ];
  const tail: TableColumnsType<MarginRow> = [
    {
      title: copy.col_state,
      dataIndex: "state",
      width: 90,
      render: (x: string) =>
        x ? <Tag color={stateColor(x)}>{valueLabel(copy, x)}</Tag> : DASH,
    },
    {
      title: copy.col_level,
      dataIndex: "level",
      width: 78,
      render: (x: string) =>
        x ? <Tag color={levelColor(x)}>{valueLabel(copy, x)}</Tag> : DASH,
    },
    {
      title: copy.col_tags,
      dataIndex: "tags",
      width: 220,
      render: (x: string) =>
        splitTags(x).map((t) => <Tag key={t}>{valueLabel(copy, t)}</Tag>),
    },
  ];
  const columns = [...base, ...(view === "lever" ? lever : struct), ...tail];

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      <KpiRow items={kpis} />
      <Panels>
        <Panel
          kind="wide"
          title={histogram ? copy.margin_hist : copy.margin_quantiles}
          extra={
            <span className="mm-muted">
              {histogram
                ? copy.margin_histNote
                : fill(copy.margin_over, {
                    a: o.n_over8 ?? DASH,
                    b: o.n_over10 ?? DASH,
                  })}
            </span>
          }
        >
          <EChart
            label={histogram ? copy.margin_hist : copy.margin_quantiles}
            option={histogram ?? quantiles}
            height={240}
          />
        </Panel>
        <Panel title={copy.margin_states}>
          <EChart
            label={copy.margin_states}
            option={stateOption}
            height={240}
          />
        </Panel>
        <Panel title={copy.margin_res}>
          <EChart label={copy.margin_res} option={resOption} height={240} />
        </Panel>
        <Panel
          kind="detail"
          title={
            <Space wrap>
              <span>{fill(copy.margin_scan, { date })}</span>
              <Segmented
                size="small"
                value={view}
                onChange={setView}
                options={[
                  { label: copy.margin_viewLever, value: "lever" },
                  { label: copy.margin_viewStruct, value: "struct" },
                ]}
              />
            </Space>
          }
        >
          <Space wrap style={{ marginBottom: 12 }}>
            <ByteSearch
              placeholder={copy.searchPlaceholder}
              width={200}
              onSearch={setSearch}
            />
            <Select
              allowClear
              placeholder={copy.col_state}
              value={state}
              onChange={setState}
              style={{ width: 120 }}
              options={valueOptions(copy, STATES)}
            />
            <Select
              allowClear
              placeholder={copy.col_level}
              value={level}
              onChange={setLevel}
              style={{ width: 110 }}
              options={valueOptions(copy, LEVELS)}
            />
            <Select
              allowClear
              placeholder={copy.margin_mechanism}
              value={mechanism}
              onChange={setMechanism}
              style={{ width: 170 }}
              options={MECHANISMS.map((name) => ({
                value: name,
                label: copy[`mech_${name}`],
              }))}
            />
            <Select
              allowClear
              placeholder={copy.col_tags}
              value={tag}
              onChange={setTag}
              style={{ width: 150 }}
              options={valueOptions(copy, TAGS)}
            />
          </Space>
          <RowTable<MarginRow>
            module="margin"
            date={date}
            revision={revision}
            columns={columns}
            defaultSort="frag"
            q={search}
            filters={filters}
            mechanism={mechanism}
            scrollX={view === "lever" ? 1320 : 1480}
            onSelect={setSelected}
          />
          <div className="mm-muted">{copy.margin_note}</div>
        </Panel>
      </Panels>
      <MarginDrawer
        code={selected?.code ?? null}
        fallback={selected}
        date={date}
        histDates={arr(summary.hist_dates)}
        kCall={summary.meta?.assumptions?.k_call}
        kLiq={summary.meta?.assumptions?.k_liq}
        onClose={() => setSelected(null)}
        copy={copy}
      />
    </Space>
  );
}

function MarginDrawer({
  code,
  fallback,
  date,
  histDates,
  kCall,
  kLiq,
  onClose,
  copy,
}: {
  code: string | null;
  fallback: MarginRow | null;
  date: string;
  histDates: string[];
  kCall: Num;
  kLiq: Num;
  onClose(): void;
  copy: Copy;
}) {
  const v = useVisual();
  const {
    row: loaded,
    detail,
    loading,
    error,
  } = useRowDetail<MarginRow, MarginDetail>("margin", code, date);
  const row = loaded ?? fallback;
  const close = arr(detail?.c);
  const balance = arr(detail?.r);
  const option = useMemo(() => {
    if (!close.length && !balance.length) return null;
    const n = Math.max(close.length, balance.length);
    const dates = histDates.slice(-n);
    const cost = row?.cost;
    const lines: {
      yAxis: number;
      label: { formatter: string };
      lineStyle: { color: string; type?: string; width?: number };
    }[] = [];
    if (isNum(cost) && cost > 0) {
      lines.push({
        yAxis: cost,
        label: { formatter: copy.drawer_cost },
        lineStyle: { ...v.threshold, type: "solid" },
      });
      if (isNum(kCall))
        lines.push({
          yAxis: +(cost * kCall).toFixed(2),
          label: { formatter: copy.drawer_callLine },
          lineStyle: v.threshold,
        });
      if (isNum(kLiq))
        lines.push({
          yAxis: +(cost * kLiq).toFixed(2),
          label: { formatter: copy.drawer_liqLine },
          lineStyle: { ...v.threshold, type: "dotted" },
        });
    }
    return {
      tooltip: { trigger: "axis" },
      legend: { top: 0 },
      grid: { left: 50, right: 56, top: 36, bottom: 30 },
      xAxis: {
        type: "category",
        data:
          dates.length === n
            ? dates
            : Array.from({ length: n }, (_, i) => String(i + 1)),
      },
      yAxis: [
        { type: "value", scale: true, name: copy.drawer_close },
        {
          type: "value",
          scale: true,
          name: copy.drawer_balance,
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: copy.drawer_close,
          type: "line",
          showSymbol: false,
          data: close,
          markLine: lines.length
            ? { silent: true, symbol: "none", data: lines }
            : undefined,
        },
        {
          name: copy.drawer_balance,
          type: "bar",
          yAxisIndex: 1,
          data: balance,
          itemStyle: { opacity: 0.35 },
        },
      ],
    };
  }, [close, balance, histDates, row?.cost, kCall, kLiq, v, copy]);
  const item = (label: string, children: React.ReactNode) => ({
    label,
    children,
  });
  const pctOr = (x: Num, d = 1, none = DASH) =>
    isNum(x) ? `${fmt(x, d)}%` : none;
  return (
    <Drawer
      size={720}
      open={!!code}
      onClose={onClose}
      title={row ? `${row.name ?? ""} ${row.code}` : ""}
    >
      {loading && <Spin aria-label={copy.loading} />}
      {error && <Alert type="error" showIcon title={copy.unavailable} />}
      {row && !loading && (
        <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
          <Space wrap>
            {row.state && (
              <Tag color={stateColor(row.state)}>
                {valueLabel(copy, row.state)}
              </Tag>
            )}
            {row.level && (
              <Tag color={levelColor(row.level)}>
                {valueLabel(copy, row.level)}
              </Tag>
            )}
            {splitTags(row.tags).map((t) => (
              <Tag key={t}>{valueLabel(copy, t)}</Tag>
            ))}
          </Space>
          {option ? (
            <EChart label={copy.drawer_chart} option={option} height={260} />
          ) : (
            <Empty description={copy.drawer_noSeries} />
          )}
          {row.res_detail ? (
            <Alert
              type="error"
              showIcon
              title={copy.drawer_resonance}
              description={row.res_detail}
            />
          ) : null}
          <Typography.Text strong>{copy.drawer_leverage}</Typography.Text>
          <Descriptions
            size="small"
            column={2}
            bordered
            items={[
              item(copy.col_ratio, pctOr(row.ratio, 2)),
              item(
                copy.col_dratio20,
                <Signed value={row.dratio20} digits={2} suffix=" pp" />,
              ),
              item(copy.drawer_rz, isNum(row.rz) ? fmt(row.rz, 2) : DASH),
              item(
                copy.drawer_rzChg20,
                <Signed value={row.rz_chg20} digits={1} suffix="%" />,
              ),
              item(copy.drawer_cost, fmt(row.cost, 2)),
              item(
                copy.col_pnl,
                <Signed value={row.pnl} digits={1} suffix="%" />,
              ),
              item(copy.col_bufCall, pctOr(row.buf_call)),
              item(copy.drawer_bufLiq, pctOr(row.buf_liq)),
              item(copy.col_score, fmt(row.score, 1)),
              item(copy.col_frag, fmt(row.frag, 1)),
              item(copy.drawer_volPct, fmt(row.vol_pct, 0)),
              item(copy.drawer_amtVr, fmt(row.amt_vr, 2)),
            ]}
          />
          <Typography.Text strong>{copy.drawer_structure}</Typography.Text>
          <Descriptions
            size="small"
            column={2}
            bordered
            items={[
              item(copy.col_pldRatio, pctOr(row.pld_ratio, 1, copy.none)),
              item(copy.col_pldRoom, pctOr(row.pld_room)),
              item(copy.col_ulk60, row.ulk60 ? pctOr(row.ulk60, 2) : copy.none),
              item(copy.drawer_ulkNext, row.ulk_next || DASH),
              item(copy.col_cbPrem, pctOr(row.cb_prem, 1, copy.none)),
              item(copy.drawer_blkDisc, pctOr(row.blk_disc)),
              item(
                copy.col_gdhsChg,
                <Signed value={row.gdhs_chg} digits={1} suffix="%" />,
              ),
              item(copy.col_fundPct, pctOr(row.fund_pct, 2)),
            ]}
          />
        </Space>
      )}
    </Drawer>
  );
}
