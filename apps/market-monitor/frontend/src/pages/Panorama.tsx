import { useCallback, useMemo, useState } from "react";
import {
  Alert,
  Card,
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
import { Dashboard } from "../components/Dashboard";
import { EChart } from "../components/EChart";
import { KpiRow, type KpiItem } from "../components/Kpi";
import { RowTable } from "../components/RowTable";
import { useVisual, type Visual } from "../components/useVisual";
import { useCopy, type Copy } from "../lib/copy";
import {
  arr,
  fill,
  fmt,
  isNum,
  pct,
  signed,
  DASH,
  type Num,
} from "../lib/format";
import { useRowDetail } from "../lib/hooks";
import { valueLabel, valueOptions } from "../lib/labels";

type Strategy = {
  name?: string;
  en?: string;
  desc?: string;
  w?: Record<string, Num>;
  templates?: { id: string; name: string; desc?: string; n?: Num }[];
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
        显著低估: "success",
        低估: "cyan",
        合理: "default",
        高估: "orange",
        显著高估: "error",
        分歧过大: "purple",
        单一方法参考: "geekblue",
        数据不足: "default",
      } as Record<string, string>
    )[label ?? ""] ?? "default"
  );
}
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
    { key: "p", title: copy.pano_period, value: meta.report_period ?? DASH },
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
    ["便宜好公司", v.successBg, v.success],
    ["优质但贵", v.fillQuaternary, v.warning],
    ["价值陷阱", v.fillQuaternary, v.orange],
    ["又贵又差", v.errorBg, v.danger],
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
        <span style={{ color: isNum(x) ? (x > 0 ? v.up : v.down) : undefined }}>
          {isNum(x) ? `${signed(x * 100, 1)}%` : DASH}
        </span>
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
        x ? <Tag color={labelColor(x)}>{valueLabel(copy, x)}</Tag> : DASH,
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
      <Row gutter={[16, 16]}>
        <Col xs={24} md={12} lg={8}>
          <Card
            size="small"
            title={copy.pano_labels}
            style={{ height: "100%" }}
          >
            {labelEntries.length ? (
              <EChart
                label={copy.pano_labels}
                option={labelOption}
                height={240}
              />
            ) : (
              <Empty description={copy.noData} />
            )}
          </Card>
        </Col>
        <Col xs={24} md={12} lg={8}>
          <Card size="small" title={copy.pano_quads} style={{ height: "100%" }}>
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
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card
            size="small"
            title={copy.pano_coverage}
            style={{ height: "100%" }}
          >
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
          </Card>
        </Col>
      </Row>
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card
            size="small"
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
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card
            size="small"
            title={copy.pano_methods}
            style={{ height: "100%" }}
          >
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
          </Card>
        </Col>
      </Row>
      <Card size="small" title={copy.pano_screener}>
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
          <ByteSearch
            placeholder={copy.pano_industryExact}
            width={170}
            onSearch={setIndustry}
          />
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
      </Card>
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
      lineStyle: { color: string };
    }[] = [];
    if (isNum(row.price))
      lines.push({
        xAxis: row.price,
        label: { formatter: `${copy.pano_price} ${fmt(row.price, 2)}` },
        lineStyle: { color: v.danger },
      });
    if (isNum(row.composite))
      lines.push({
        xAxis: row.composite,
        label: { formatter: copy.pano_composite },
        lineStyle: { color: v.success },
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
              <Tag color={labelColor(row.label)}>
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
                    isNum(row.upside)
                      ? `${signed(row.upside * 100, 1)}%`
                      : DASH,
                  ),
                  item("PE / PB", `${fmt(row.pe, 1)} / ${fmt(row.pb, 2)}`),
                  item("ROE", isNum(row.roe) ? `${fmt(row.roe, 1)}%` : DASH),
                  item(
                    copy.pano_growth,
                    `${signed(row.rev_yoy, 1)}% / ${signed(row.np_yoy, 1)}%`,
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
