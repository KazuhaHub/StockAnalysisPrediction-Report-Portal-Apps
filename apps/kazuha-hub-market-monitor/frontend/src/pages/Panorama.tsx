import { useCallback, useMemo, useState } from "react";
import {
  Alert,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Progress,
  Row,
  Segmented,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Tooltip,
} from "antd";
import type { TableColumnsType } from "antd";
import { ByteSearch } from "../components/ByteSearch";
import { Panel, Panels } from "../components/Panels";
import { Dashboard } from "../components/Dashboard";
import { EChart } from "../components/EChart";
import { KpiRow, type KpiItem } from "../components/Kpi";
import { RowTable } from "../components/RowTable";
import { Signed } from "../components/Signed";
import { tagProps } from "../lib/status";
import { useVisual, type Visual } from "../components/useVisual";
import { useCopy, type Copy } from "../lib/copy";
import { arr, fill, fmt, isNum, pct, DASH, type Num } from "../lib/format";
import { useMediaQuery, useRowDetail } from "../lib/hooks";
import { valueLabel, valueOptions } from "../lib/labels";
import { escapeHtml } from "../lib/html";

type Strategy = {
  name?: string;
  en?: string;
  desc?: string;
  w?: Record<string, Num>;
  templates?: { id: string; name: string; desc?: string; n?: Num }[];
};
type Industry = {
  name: string;
  n?: Num;
  mktcap?: Num;
  [key: string]: unknown;
};
/**
 * The strategy axis labels of the heatmap: every name is shown, level on a wide
 * screen and turned 45 degrees on a narrow one, where six level names overlap.
 */
export function heatStrategyLabel(narrow: boolean) {
  return { interval: 0, fontSize: 10, rotate: narrow ? 45 : 0 };
}

/**
 * Heatmap row order: market cap descending, industries without one after the
 * rest, ties (and snapshots without market caps) by stock count descending.
 */
export function heatOrder(industries: Industry[]): Industry[] {
  const cap = (i: Industry) => (isNum(i.mktcap) ? i.mktcap : -Infinity);
  const count = (i: Industry) => (isNum(i.n) ? i.n : 0);
  // An industry without a name would be a blank, unlabelled row.
  return industries
    .filter((i) => typeof i.name === "string" && i.name !== "")
    .sort((a, b) => cap(b) - cap(a) || count(b) - count(a));
}
type ShiftRow = {
  s: string;
  n?: string;
  a?: Num;
  b?: Num;
  la?: string;
  lb?: string;
};
type PanoramaSummary = {
  meta?: {
    report_period?: string;
    n_universe?: Num;
    n_pool?: Num;
    n_valid?: Num;
    n_factors?: Num;
    labels?: Record<string, Num>;
    quads?: Record<string, Num>;
    profiles?: Record<string, Num>;
    coverage?: Record<string, { n?: Num; mean?: Num }>;
  };
  factors?: { id: string; name?: string }[];
  strategies?: Record<string, Strategy>;
  methods?: { id: string; name?: string; weight?: Num; cov?: Num }[];
  // Newer snapshots only: every part built from these must cope with absence.
  industries?: Industry[];
  market?: {
    median_pe?: Num;
    median_pb?: Num;
    above_ma120_pct?: Num;
  };
  diff?: {
    first?: boolean;
    prev?: string;
    cur?: string;
    shift?: ShiftRow[];
  };
};
export type PanoramaRow = {
  code: string;
  name?: string;
  sw1?: string;
  label?: string;
  quad?: string;
  profile?: string;
  price?: Num;
  pe?: Num;
  pb?: Num;
  roe?: Num;
  composite?: Num;
  upside?: Num;
  n_methods?: Num;
  resonance?: Num;
  disp?: Num;
  div_yield?: Num;
  rev_yoy?: Num;
  np_yoy?: Num;
  implied_g?: Num;
  [key: string]: unknown;
};

const STRATS = [
  "value",
  "growth",
  "cyclical",
  "dividend",
  "momentum",
  "quality",
] as const;
type Strat = (typeof STRATS)[number];

function labelColor(label: string | undefined): string {
  return (
    (
      {
        // Statuses, not signs (docs/charts.md): opportunity blue, warning amber.
        显著低估: "processing",
        低估: "cyan",
        合理: "default",
        高估: "gold",
        显著高估: "orange-inverse",
        分歧过大: "purple",
        单一方法参考: "geekblue",
        数据不足: "default",
      } as Record<string, string>
    )[label ?? ""] ?? "default"
  );
}
const UNCLASSIFIED = "未分类";
const num = (row: PanoramaRow, key: string): Num =>
  isNum(row[key]) ? (row[key] as number) : null;

export function PanoramaPage() {
  const { copy } = useCopy();
  return (
    <Dashboard<PanoramaSummary> module="panorama" title={copy.panoramaTitle}>
      {(ctx) => <PanoramaBody {...ctx} />}
    </Dashboard>
  );
}

function PanoramaBody({
  summary,
  date,
  revision,
}: {
  summary: PanoramaSummary;
  date: string;
  revision: number;
}) {
  const { copy } = useCopy();
  const v = useVisual();
  const meta = summary.meta ?? {};
  const [strat, setStrat] = useState<Strat>("value");
  const [search, setSearch] = useState("");
  const [label, setLabel] = useState<string>();
  const [quad, setQuad] = useState<string>();
  const [profile, setProfile] = useState<string>();
  const [industry, setIndustry] = useState("");
  const [selected, setSelected] = useState<PanoramaRow | null>(null);
  const filters = useMemo(
    () => ({ label, quad, profile, sw1: industry || undefined }),
    [label, quad, profile, industry],
  );
  const stratName = useCallback(
    // Locale copy first: the snapshot's names are simplified Chinese only.
    (key: Strat) =>
      copy[`strat_${key}`] ?? summary.strategies?.[key]?.name ?? key,
    [summary.strategies, copy],
  );
  const current = summary.strategies?.[strat];
  const factorNames = useMemo(
    () =>
      Object.fromEntries(
        arr(summary.factors).map((f) => [f.id, f.name ?? f.id]),
      ),
    [summary.factors],
  );

  const market = summary.market;
  const kpis: KpiItem[] = [
    {
      key: "u",
      title: copy.pano_universe,
      value: isNum(meta.n_universe) ? String(meta.n_universe) : DASH,
    },
    {
      key: "valid",
      title: copy.pano_valid,
      value: isNum(meta.n_valid) ? String(meta.n_valid) : DASH,
    },
    // Market-level readings replace the pool and factor counts when the
    // snapshot carries them (six cards per row); older snapshots keep both.
    ...(market
      ? [
          {
            key: "pe",
            title: copy.pano_medianPe,
            value: isNum(market.median_pe)
              ? `${market.median_pe.toFixed(1)}×`
              : DASH,
          },
          {
            key: "pb",
            title: copy.pano_medianPb,
            value: isNum(market.median_pb)
              ? `${market.median_pb.toFixed(2)}×`
              : DASH,
          },
          {
            key: "ma",
            title: copy.pano_aboveMa120,
            value: isNum(market.above_ma120_pct)
              ? `${market.above_ma120_pct.toFixed(1)}%`
              : DASH,
          },
        ]
      : [
          {
            key: "pool",
            title: copy.pano_pool,
            value: isNum(meta.n_pool) ? String(meta.n_pool) : DASH,
          },
          {
            key: "f",
            title: copy.pano_factors,
            value: isNum(meta.n_factors) ? String(meta.n_factors) : DASH,
          },
        ]),
    { key: "p", title: copy.pano_period, value: meta.report_period ?? DASH },
  ];
  const industryNames = useMemo(
    () =>
      arr(summary.industries)
        .map((i) => i.name)
        .filter((n): n is string => typeof n === "string" && n !== ""),
    [summary.industries],
  );
  // Industries by market cap, largest first; an industry with no score is
  // kept as a blank row.
  const narrow = useMediaQuery("(max-width: 575px)");
  const heatIndustries = useMemo(
    () => heatOrder(arr(summary.industries)),
    [summary.industries],
  );
  const heatOption = useMemo(() => {
    const names = STRATS.map((k) => stratName(k));
    const data: [number, number, number][] = [];
    heatIndustries.forEach((it, y) =>
      STRATS.forEach((k, x) => {
        const score = it[`s_${k}`];
        // A missing score is a blank cell, not a zero.
        if (isNum(score)) data.push([x, y, score]);
      }),
    );
    return {
      tooltip: {
        formatter: (p: { value: [number, number, number] }) =>
          fill(copy.pano_heatTip, {
            industry: escapeHtml(heatIndustries[p.value[1]]?.name),
            strategy: escapeHtml(names[p.value[0]]),
            score: fmt(p.value[2], 1),
          }),
      },
      // Turned labels need more room above the grid.
      grid: { left: 84, right: 10, top: narrow ? 56 : 28, bottom: 10 },
      xAxis: {
        type: "category",
        data: names,
        position: "top",
        // Show every strategy name; the default skips labels that would touch.
        axisLabel: heatStrategyLabel(narrow),
        splitArea: { show: false },
      },
      yAxis: {
        type: "category",
        inverse: true,
        data: heatIndustries.map((i) => i.name),
      },
      // Diverging around 50: below is cool, above is warm.
      visualMap: {
        min: 30,
        max: 70,
        show: false,
        // Percentiles, not signs: a blue-to-amber scale, never red/green.
        inRange: { color: [v.primary, v.surface, v.orange] },
      },
      series: [
        {
          type: "heatmap",
          data,
          label: {
            show: true,
            formatter: (p: { value: [number, number, number] }) =>
              fmt(p.value[2], 0),
            fontSize: 10,
          },
          itemStyle: { borderColor: v.surface, borderWidth: 1 },
        },
      ],
    };
  }, [heatIndustries, stratName, copy, v, narrow]);
  const shift = useMemo(
    () =>
      summary.diff && !summary.diff.first
        ? arr(summary.diff.shift).slice(0, 6)
        : [],
    [summary.diff],
  );
  const pctCell = (x: Num) => (
    <Signed value={x} scale={100} digits={1} suffix="%" />
  );
  const shiftColumns: TableColumnsType<ShiftRow> = [
    {
      title: copy.col_name,
      render: (_, r) => `${r.n ?? ""} ${r.s}`.trim(),
    },
    {
      title: copy.pano_prevUpside,
      dataIndex: "a",
      align: "right",
      render: pctCell,
    },
    {
      title: copy.pano_curUpside,
      dataIndex: "b",
      align: "right",
      render: pctCell,
    },
    {
      title: copy.pano_label,
      render: (_, r) =>
        !r.lb
          ? DASH
          : r.la && r.la !== r.lb
            ? `${valueLabel(copy, r.la)} → ${valueLabel(copy, r.lb)}`
            : valueLabel(copy, r.lb),
    },
  ];
  const labelEntries = useMemo(
    () => Object.entries(meta.labels ?? {}),
    [meta.labels],
  );
  const labelOption = useMemo(
    () => ({
      tooltip: { trigger: "item" },
      series: [
        {
          type: "pie",
          radius: ["40%", "68%"],
          label: { formatter: "{b} {c}" },
          data: labelEntries.map(([name, value]) => ({
            name: valueLabel(copy, name),
            value,
          })),
        },
      ],
    }),
    [labelEntries, copy],
  );
  const weights = useMemo(
    () =>
      Object.entries(current?.w ?? {})
        .filter(([, w]) => isNum(w))
        .sort((a, b) => (b[1] as number) - (a[1] as number)),
    [current],
  );
  const weightOption = useMemo(
    () => ({
      tooltip: {},
      grid: { left: 130, right: 40, top: 10, bottom: 20 },
      xAxis: { type: "value" },
      yAxis: {
        type: "category",
        inverse: true,
        data: weights.map(([id]) => factorNames[id] ?? id),
      },
      series: [
        {
          type: "bar",
          data: weights.map(([, w]) => w),
          itemStyle: { color: v.primary },
          label: { show: true, position: "right" },
        },
      ],
    }),
    [weights, factorNames, v],
  );
  const quadCells: [string, string, string][] = [
    // Statuses, not signs: opportunity blue, warnings amber to strong orange.
    ["便宜好公司", v.fillQuaternary, v.primary],
    ["优质但贵", v.fillQuaternary, v.orange],
    ["价值陷阱", v.fillQuaternary, v.purple],
    ["又贵又差", v.fillQuaternary, v.alert],
  ];

  const columns: TableColumnsType<PanoramaRow> = [
    { title: copy.col_code, dataIndex: "code", width: 80, fixed: "left" },
    { title: copy.col_name, dataIndex: "name", width: 96, fixed: "left" },
    { title: copy.pano_industry, dataIndex: "sw1", width: 92, sorter: true },
    {
      title: `${stratName(strat)} ${copy.pano_score}`,
      dataIndex: `s_${strat}`,
      width: 120,
      sorter: true,
      render: (x: Num) => (
        <Progress
          percent={isNum(x) ? Math.round(x) : 0}
          size="small"
          format={() => fmt(x, 0)}
        />
      ),
    },
    {
      title: copy.pano_resonance,
      dataIndex: "resonance",
      align: "right",
      width: 84,
      sorter: true,
      render: (x: Num) => fmt(x, 1),
    },
    {
      title: "PE",
      dataIndex: "pe",
      align: "right",
      width: 72,
      sorter: true,
      render: (x: Num) => fmt(x, 1),
    },
    {
      title: "PB",
      dataIndex: "pb",
      align: "right",
      width: 68,
      sorter: true,
      render: (x: Num) => fmt(x, 2),
    },
    {
      title: "ROE",
      dataIndex: "roe",
      align: "right",
      width: 72,
      sorter: true,
      render: (x: Num) => fmt(x, 1),
    },
    {
      title: copy.pano_composite,
      dataIndex: "composite",
      align: "right",
      width: 84,
      sorter: true,
      render: (x: Num) => fmt(x, 2),
    },
    {
      title: copy.pano_upside,
      dataIndex: "upside",
      align: "right",
      width: 92,
      sorter: true,
      render: (x: Num) => (
        <Signed value={x} scale={100} digits={1} suffix="%" />
      ),
    },
    {
      title: copy.pano_nMethods,
      dataIndex: "n_methods",
      align: "right",
      width: 84,
      sorter: true,
    },
    {
      title: copy.pano_label,
      dataIndex: "label",
      width: 110,
      render: (x: string) =>
        x ? (
          <Tag {...tagProps(labelColor(x))}>{valueLabel(copy, x)}</Tag>
        ) : (
          DASH
        ),
    },
    {
      title: copy.pano_quad,
      dataIndex: "quad",
      width: 100,
      render: (x: string) => (x ? valueLabel(copy, x) : DASH),
    },
  ];

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      <KpiRow items={kpis} cols={{ xs: 12, md: 8, xl: 4 }} />
      <Panels>
        {heatIndustries.length > 0 && (
          <Panel kind="wide" title={copy.pano_heat}>
            <EChart
              label={copy.pano_heat}
              option={heatOption}
              height={heatIndustries.length * 22 + 40}
            />
          </Panel>
        )}
        <Panel title={copy.pano_labels}>
          {labelEntries.length ? (
            <EChart
              label={copy.pano_labels}
              option={labelOption}
              height={240}
            />
          ) : (
            <Empty description={copy.noData} />
          )}
        </Panel>
        <Panel title={copy.pano_quads}>
          <Row gutter={[8, 8]}>
            {quadCells.map(([name, bg, fg]) => (
              <Col span={12} key={name}>
                <div className="mm-quad" style={{ background: bg }}>
                  <div style={{ color: fg, fontSize: 24, fontWeight: 600 }}>
                    {isNum(meta.quads?.[name]) ? meta.quads[name] : DASH}
                  </div>
                  <div className="mm-muted">{valueLabel(copy, name)}</div>
                </div>
              </Col>
            ))}
          </Row>
          <div className="mm-muted" style={{ marginTop: 8 }}>
            {copy.pano_quadNote}
          </div>
        </Panel>
        <Panel title={copy.pano_coverage}>
          {STRATS.map((key) => (
            <div key={key} className="mm-between">
              <span style={{ minWidth: 56 }}>{stratName(key)}</span>
              <Progress
                size="small"
                percent={
                  isNum(meta.coverage?.[key]?.mean)
                    ? Math.round(meta.coverage[key].mean! * 100)
                    : 0
                }
                style={{ flex: 1, marginLeft: 12 }}
              />
            </div>
          ))}
        </Panel>
        {shift.length > 0 && (
          <Panel
            kind="detail"
            title={
              <Space wrap>
                <span>{copy.pano_shift}</span>
                <span className="mm-muted">
                  {summary.diff?.prev} → {summary.diff?.cur}
                </span>
              </Space>
            }
          >
            <Table<ShiftRow>
              size="small"
              pagination={false}
              rowKey="s"
              dataSource={shift}
              columns={shiftColumns}
              onRow={(r) => ({
                onClick: () => setSelected({ code: r.s, name: r.n }),
                style: { cursor: "pointer" },
              })}
            />
          </Panel>
        )}
        <Panel
          title={
            <Space wrap>
              <span>{copy.pano_strategy}</span>
              <Segmented
                size="small"
                value={strat}
                onChange={setStrat}
                options={STRATS.map((key) => ({
                  value: key,
                  label: stratName(key),
                }))}
              />
            </Space>
          }
        >
          {current?.desc && (
            <div style={{ marginBottom: 8 }}>{current.desc}</div>
          )}
          <Space wrap style={{ marginBottom: 8 }}>
            {arr(current?.templates).map((t) => (
              <Tooltip key={t.id} title={t.desc}>
                <Tag color="blue">
                  {t.name} · {t.n ?? DASH}
                </Tag>
              </Tooltip>
            ))}
          </Space>
          {weights.length ? (
            <EChart
              label={copy.pano_weights}
              option={weightOption}
              height={Math.max(180, weights.length * 28 + 30)}
            />
          ) : (
            <Empty description={copy.noData} />
          )}
        </Panel>
        <Panel title={copy.pano_methods}>
          <Table
            size="small"
            pagination={false}
            rowKey="id"
            dataSource={arr(summary.methods)}
            columns={[
              { title: copy.pano_method, dataIndex: "name" },
              {
                title: copy.pano_weight,
                dataIndex: "weight",
                align: "right",
                render: (x: Num) => fmt(x, 1),
              },
              { title: copy.pano_cov, dataIndex: "cov", align: "right" },
            ]}
          />
        </Panel>
        <Panel kind="detail" title={copy.pano_screener}>
          <Space wrap style={{ marginBottom: 12 }}>
            <ByteSearch
              placeholder={copy.searchPlaceholder}
              width={200}
              onSearch={setSearch}
            />
            <Select
              allowClear
              placeholder={copy.pano_label}
              value={label}
              onChange={setLabel}
              style={{ width: 130 }}
              options={valueOptions(copy, Object.keys(meta.labels ?? {}))}
            />
            <Select
              allowClear
              placeholder={copy.pano_quad}
              value={quad}
              onChange={setQuad}
              style={{ width: 130 }}
              options={valueOptions(copy, Object.keys(meta.quads ?? {}))}
            />
            <Select
              allowClear
              placeholder={copy.pano_profile}
              value={profile}
              onChange={setProfile}
              style={{ width: 110 }}
              options={valueOptions(copy, Object.keys(meta.profiles ?? {}))}
            />
            {industryNames.length > 0 ? (
              <Select
                allowClear
                showSearch
                placeholder={copy.pano_industry}
                value={industry || undefined}
                onChange={(x?: string) => setIndustry(x ?? "")}
                style={{ width: 150 }}
                // The industry list leaves out unclassified stocks; keep them
                // filterable as the exact-name search allowed.
                options={[...new Set([...industryNames, UNCLASSIFIED])].map(
                  (name) => ({
                    value: name,
                    label:
                      name === UNCLASSIFIED ? copy.pano_unclassified : name,
                  }),
                )}
              />
            ) : (
              <ByteSearch
                placeholder={copy.pano_industryExact}
                width={170}
                onSearch={setIndustry}
              />
            )}
          </Space>
          <RowTable<PanoramaRow>
            module="panorama"
            date={date}
            revision={revision}
            columns={columns}
            defaultSort={`s_${strat}`}
            q={search}
            filters={filters}
            scrollX={1260}
            onSelect={setSelected}
          />
        </Panel>
      </Panels>
      <PanoramaDrawer
        code={selected?.code ?? null}
        fallback={selected}
        date={date}
        methods={arr(summary.methods)}
        stratName={stratName}
        onClose={() => setSelected(null)}
        copy={copy}
      />
    </Space>
  );
}

function PanoramaDrawer({
  code,
  fallback,
  date,
  methods,
  stratName,
  onClose,
  copy,
}: {
  code: string | null;
  fallback: PanoramaRow | null;
  date: string;
  methods: NonNullable<PanoramaSummary["methods"]>;
  stratName(key: Strat): string;
  onClose(): void;
  copy: Copy;
}) {
  const v: Visual = useVisual();
  const {
    row: loaded,
    loading,
    error,
  } = useRowDetail<PanoramaRow, unknown>("panorama", code, date);
  const row = loaded ?? fallback;
  const present = useMemo(
    () => methods.filter((m) => row && `v_${m.id}` in row),
    [methods, row],
  );
  const methodOption = useMemo(() => {
    if (!row || !present.length) return null;
    const lines: {
      xAxis: number;
      label: { formatter: string };
      lineStyle: { color: string; type?: string; width?: number };
    }[] = [];
    if (isNum(row.price))
      lines.push({
        xAxis: row.price,
        label: { formatter: `${copy.pano_price} ${fmt(row.price, 2)}` },
        lineStyle: { color: v.primary, width: 2 },
      });
    if (isNum(row.composite))
      lines.push({
        xAxis: row.composite,
        label: { formatter: copy.pano_composite },
        lineStyle: { color: v.orange, type: "dashed", width: 2 },
      });
    return {
      tooltip: {},
      grid: { left: 120, right: 60, top: 10, bottom: 30 },
      xAxis: { type: "value", scale: true },
      yAxis: {
        type: "category",
        inverse: true,
        data: present.map((m) => m.name ?? m.id),
      },
      series: [
        {
          type: "bar",
          data: present.map((m) => {
            const x = num(row, `v_${m.id}`);
            return isNum(x) ? +x.toFixed(2) : null;
          }),
          itemStyle: { color: v.primary },
          label: { show: true, position: "right" },
          markLine: { silent: true, symbol: "none", data: lines },
        },
      ],
    };
  }, [row, present, v, copy]);
  // A strategy without a score is missing, not zero: it gets no radar axis
  // and is named in a note instead.
  const scores = useMemo(
    () =>
      STRATS.map((key) => ({
        key,
        name: stratName(key),
        score: row ? num(row, `s_${key}`) : null,
      })),
    [row, stratName],
  );
  const scored = scores.filter((x) => isNum(x.score));
  const missingNames = scores
    .filter((x) => !isNum(x.score))
    .map((x) => x.name)
    .join(", ");
  const radarOption = useMemo(() => {
    const axes = scores.filter((x) => isNum(x.score));
    // A radar needs at least three axes to be a polygon.
    if (axes.length < 3) return null;
    return {
      radar: {
        indicator: axes.map((x) => ({ name: x.name, max: 100 })),
        radius: "62%",
      },
      series: [
        {
          type: "radar",
          data: [
            {
              value: axes.map((x) => x.score),
              areaStyle: { opacity: 0.2 },
            },
          ],
        },
      ],
    };
  }, [scores]);
  const item = (label: string, children: React.ReactNode) => ({
    label,
    children,
  });
  return (
    <Drawer
      size={720}
      open={!!code}
      onClose={onClose}
      title={
        row
          ? `${row.name ?? ""} ${row.code}${row.sw1 ? ` · ${row.sw1}` : ""}`
          : ""
      }
    >
      {loading && <Spin aria-label={copy.loading} />}
      {error && <Alert type="error" showIcon title={copy.unavailable} />}
      {row && !loading && (
        <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
          <Space wrap>
            {row.label && (
              <Tag {...tagProps(labelColor(row.label))}>
                {valueLabel(copy, row.label)}
              </Tag>
            )}
            {row.quad && <Tag>{valueLabel(copy, row.quad)}</Tag>}
            {row.profile && <Tag>{valueLabel(copy, row.profile)}</Tag>}
            <span className="mm-muted">
              {copy.pano_nMethods} {isNum(row.n_methods) ? row.n_methods : DASH}{" "}
              · {copy.pano_disp} {fmt(row.disp, 2)}
            </span>
          </Space>
          <b>{copy.pano_methodsDrawer}</b>
          {methodOption ? (
            <EChart
              label={copy.pano_methodsDrawer}
              option={methodOption}
              height={Math.max(220, present.length * 30 + 50)}
            />
          ) : (
            <Empty description={copy.noData} />
          )}
          <Row gutter={16}>
            <Col span={24} md={11}>
              <b>{copy.pano_radar}</b>
              {radarOption ? (
                <EChart
                  label={copy.pano_radar}
                  option={radarOption}
                  height={240}
                />
              ) : (
                <ul className="mm-muted">
                  {scored.map((x) => (
                    <li key={x.key}>
                      {x.name}: {fmt(x.score, 0)}
                    </li>
                  ))}
                  {scored.length === 0 && <li>{copy.noData}</li>}
                </ul>
              )}
              {missingNames && (
                <div className="mm-muted">
                  {fill(copy.pano_radarMissing, { names: missingNames })}
                </div>
              )}
            </Col>
            <Col span={24} md={13}>
              <Descriptions
                size="small"
                column={1}
                bordered
                items={[
                  item(copy.pano_price, fmt(row.price, 2)),
                  item(copy.pano_composite, fmt(row.composite, 2)),
                  item(
                    copy.pano_upside,
                    <Signed
                      value={row.upside}
                      scale={100}
                      digits={1}
                      suffix="%"
                    />,
                  ),
                  item("PE / PB", `${fmt(row.pe, 1)} / ${fmt(row.pb, 2)}`),
                  item("ROE", isNum(row.roe) ? `${fmt(row.roe, 1)}%` : DASH),
                  item(
                    copy.pano_growth,
                    <>
                      <Signed value={row.rev_yoy} digits={1} suffix="%" /> /{" "}
                      <Signed value={row.np_yoy} digits={1} suffix="%" />
                    </>,
                  ),
                  item(
                    copy.pano_dividend,
                    isNum(row.div_yield) ? `${fmt(row.div_yield, 2)}%` : DASH,
                  ),
                  item(copy.pano_impliedG, pct(row.implied_g)),
                ]}
              />
            </Col>
          </Row>
        </Space>
      )}
    </Drawer>
  );
}
