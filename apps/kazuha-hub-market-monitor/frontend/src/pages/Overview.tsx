import { useMemo } from "react";
import { Alert, Button, Card, Col, Empty, Row, Space, Tag } from "antd";
import { useAppNavigation } from "@portal-app/sdk/root-v2";
import { Panel, Panels } from "../components/Panels";
import { Dashboard, ROUTES } from "../components/Dashboard";
import { EChart } from "../components/EChart";
import { KpiRow, type KpiItem } from "../components/Kpi";
import { useVisual } from "../components/useVisual";
import { useCopy } from "../lib/copy";
import { TAG_COLOR, tagText } from "../lib/quant";
import {
  arr,
  fill,
  fmt,
  formatYi,
  isNum,
  rollingSum,
  DASH,
  type Num,
} from "../lib/format";

type RiskSummary = {
  margin?: {
    as_of?: string;
    lever_ratio?: Num;
    guarantee?: Num;
    lever_series?: { d?: string[]; rz?: Num[]; ratio?: Num[] };
    guarantee_series?: { d?: string[]; v?: Num[] };
    n_res2?: Num;
    n_critical?: Num;
    n_high?: Num;
    n_pledge_near?: Num;
    n_pledge_breach?: Num;
    n_unlock60?: Num;
    n_cb_arb?: Num;
    n_block?: Num;
    n_gdhs_dump?: Num;
  };
  sentiment?: {
    as_of?: string;
    headline?: string;
    breadth?: Num;
    breadth_series?: { dates?: string[]; values?: Num[] };
  };
  etf?: {
    as_of?: string;
    current?: { last20?: Num; last_nf?: Num };
    health?: { label?: string; light?: string };
    nf_series?: { dates?: string[]; nf?: Num[] };
  };
  /** Optional: absent until the quant job has produced a snapshot. */
  quant?: {
    as_of?: string;
    state?: string;
    state_code?: string;
    breadth?: Num;
    ndr?: Num;
    /** Positions are percents: 0, 25, 50 or 100. */
    step_pos?: Num;
    step_stage?: Num;
    step_cap?: boolean | Num;
    micro_state?: string;
    micro_code?: string;
    micro_pos?: Num;
  };
  inputs?: Record<string, string>;
};

export function OverviewPage() {
  const { copy } = useCopy();
  return (
    <Dashboard<RiskSummary> module="risk" title={copy.title}>
      {({ summary, asOf }) => <OverviewBody r={summary} asOf={asOf} />}
    </Dashboard>
  );
}

function OverviewBody({ r, asOf }: { r: RiskSummary; asOf: string }) {
  const { copy, locale } = useCopy();
  const v = useVisual();
  const navigation = useAppNavigation();
  const m = r.margin;
  const s = r.sentiment;
  const e = r.etf;
  const nf20 = useMemo(
    () => rollingSum(arr(e?.nf_series?.nf), 20),
    [e?.nf_series],
  );
  const lever = m?.lever_series;
  const leverSpark = useMemo(
    () => arr(lever?.ratio).slice(-120),
    [lever?.ratio],
  );
  const guarantee = m?.guarantee_series;

  const kpis: KpiItem[] = [
    {
      key: "lever",
      title: copy.ov_lever,
      value: isNum(m?.lever_ratio) ? `${fmt(m.lever_ratio, 2)}%` : DASH,
      note: `${copy.nav_margin} · ${copy.ov_leverNote}`,
      spark: { data: leverSpark, color: v.purple },
    },
    {
      key: "guar",
      title: copy.ov_guarantee,
      value: isNum(m?.guarantee) ? `${fmt(m.guarantee, 1)}%` : DASH,
      note: `${copy.nav_margin} · ${copy.ov_guaranteeNote}`,
      spark: { data: arr(guarantee?.v), color: v.cyan },
    },
    {
      key: "breadth",
      title: copy.ov_breadth,
      value: fmt(s?.breadth, 1),
      note: `${copy.nav_sentiment} · ${copy.ov_breadthNote}`,
      spark: { data: arr(s?.breadth_series?.values), color: v.primary },
      tag:
        isNum(s?.breadth) && s.breadth < 20
          ? { text: copy.ov_cold, color: "processing" }
          : undefined,
    },
    {
      key: "etf",
      title: copy.ov_etf20,
      // A net flow: signed, red inflow, green outflow.
      value:
        (isNum(e?.current?.last20) && e.current.last20 > 0 ? "+" : "") +
        formatYi(e?.current?.last20, locale),
      color: v.sign(e?.current?.last20),
      note: `${copy.nav_etf} · ${copy.ov_etfNote}`,
      spark: { data: nf20, color: v.orange },
      tag: e?.health?.label
        ? {
            text: e.health.label,
            color: v.statusTag[e.health.light ?? ""] ?? "default",
          }
        : undefined,
    },
    {
      key: "res2",
      title: copy.ov_res2,
      value: isNum(m?.n_res2) ? fill(copy.ov_count, { n: m.n_res2 }) : DASH,
      note: `${copy.nav_margin} · ${copy.ov_res2Note}`,
    },
    {
      key: "crit",
      title: copy.ov_critical,
      value: isNum(m?.n_critical)
        ? fill(copy.ov_count, { n: m.n_critical })
        : DASH,
      note: `${copy.nav_margin} · ${copy.ov_criticalNote}`,
    },
  ];

  const crossOption = useMemo(() => {
    const dates = arr(s?.breadth_series?.dates);
    if (!dates.length) return null;
    const flow = new Map(arr(e?.nf_series?.dates).map((d, i) => [d, nf20[i]]));
    return {
      tooltip: { trigger: "axis" },
      legend: { top: 0 },
      grid: { left: 50, right: 64, top: 36, bottom: 30 },
      xAxis: { type: "category", data: dates },
      yAxis: [
        { type: "value", name: copy.ov_breadthAxis, min: 0, max: 100 },
        { type: "value", name: copy.ov_etfAxis, splitLine: { show: false } },
      ],
      series: [
        {
          name: copy.ov_etf20,
          type: "bar",
          yAxisIndex: 1,
          // Net flows: red inflow, green outflow; secondary (right axis), so light.
          data: dates.map((d) => {
            const x = flow.get(d) ?? null;
            return {
              value: x,
              itemStyle: {
                color: isNum(x) && x < 0 ? v.down : v.up,
                opacity: 0.45,
              },
            };
          }),
          itemStyle: { color: v.series[4], opacity: 0.45 },
        },
        {
          name: copy.ov_breadth,
          type: "line",
          showSymbol: false,
          data: arr(s?.breadth_series?.values),
          lineStyle: { width: 2, color: v.primary },
          itemStyle: { color: v.primary },
        },
      ],
    };
  }, [s, e, nf20, v, copy]);
  const leverOption = useMemo(() => {
    if (!arr(lever?.d).length) return null;
    return {
      tooltip: { trigger: "axis" },
      legend: { top: 0 },
      grid: { left: 56, right: 50, top: 36, bottom: 30 },
      xAxis: { type: "category", data: arr(lever?.d) },
      yAxis: [
        { type: "value", name: copy.unit_yi, splitLine: { show: false } },
        { type: "value", name: "%", scale: true },
      ],
      series: [
        {
          name: copy.ov_rz,
          type: "line",
          areaStyle: { opacity: 0.15 },
          showSymbol: false,
          data: arr(lever?.rz),
        },
        {
          name: copy.ov_lever,
          type: "line",
          yAxisIndex: 1,
          showSymbol: false,
          data: arr(lever?.ratio),
        },
      ],
    };
  }, [lever, copy]);
  const guaranteeOption = useMemo(() => {
    if (!arr(guarantee?.d).length) return null;
    return {
      tooltip: { trigger: "axis" },
      grid: { left: 50, right: 20, top: 20, bottom: 30 },
      xAxis: { type: "category", data: arr(guarantee?.d) },
      yAxis: { type: "value", scale: true, name: "%" },
      series: [
        {
          name: copy.ov_guarantee,
          type: "line",
          showSymbol: false,
          data: arr(guarantee?.v),
          areaStyle: { opacity: 0.08 },
        },
      ],
    };
  }, [guarantee, copy]);
  const mech: [string, Num | undefined][] = [
    [copy.ov_mech_pledgeNear, m?.n_pledge_near],
    [copy.ov_mech_pledgeBreach, m?.n_pledge_breach],
    [copy.ov_mech_unlock, m?.n_unlock60],
    [copy.ov_mech_cb, m?.n_cb_arb],
    [copy.ov_mech_block, m?.n_block],
    [copy.ov_mech_gdhs, m?.n_gdhs_dump],
    [copy.ov_res2, m?.n_res2],
    [copy.ov_critical, m?.n_critical],
  ];
  const mechOption = useMemo(
    () => ({
      tooltip: {},
      grid: { left: 110, right: 40, top: 10, bottom: 20 },
      xAxis: { type: "value" },
      yAxis: {
        type: "category",
        inverse: true,
        data: mech.map(([name]) => name),
      },
      series: [
        {
          type: "bar",
          data: mech.map(([, n]) => (isNum(n) ? n : null)),
          itemStyle: { color: v.primary, opacity: 0.8 },
          label: { show: true, position: "right" },
        },
      ],
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }),
    [m, v, copy],
  );

  const inputs = Object.entries(r.inputs ?? {});
  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      {s?.headline && (
        <Alert
          type="warning"
          showIcon
          title={`${copy.ov_reading} · ${asOf}`}
          description={s.headline}
        />
      )}
      {inputs.length > 0 && (
        <div className="mm-muted">
          {copy.ov_inputs}:{" "}
          {inputs
            .map(([k, d]) => `${copy[`nav_${k}` as "nav_margin"] ?? k} ${d}`)
            .join(" · ")}
        </div>
      )}
      <KpiRow items={kpis} cols={{ xs: 24, sm: 12, lg: 8, xl: 8, xxl: 4 }} />
      {r.quant?.state && (
        <QuantCard
          q={r.quant}
          ready={navigation.ready}
          open={() => {
            navigation.navigate("/quant");
          }}
        />
      )}
      <Card
        size="small"
        title={copy.ov_cross}
        extra={<span className="mm-muted">{copy.ov_crossNote}</span>}
      >
        {crossOption ? (
          <EChart label={copy.ov_cross} option={crossOption} height={300} />
        ) : (
          <Empty description={copy.noData} />
        )}
      </Card>
      <Panels>
        <Panel title={copy.ov_leverChart}>
          {leverOption ? (
            <EChart label={copy.ov_leverChart} option={leverOption} />
          ) : (
            <Empty description={copy.noData} />
          )}
        </Panel>
        <Panel title={copy.ov_guarantee}>
          {guaranteeOption ? (
            <EChart label={copy.ov_guarantee} option={guaranteeOption} />
          ) : (
            <Empty description={copy.noData} />
          )}
        </Panel>
        <Panel title={copy.ov_mech}>
          {m ? (
            <EChart label={copy.ov_mech} option={mechOption} />
          ) : (
            <Empty description={copy.noData} />
          )}
        </Panel>
        <Panel kind="wide" title={copy.ov_dashboards}>
          <Space wrap>
            {ROUTES.filter((route) => route.path !== "/").map((route) => (
              <Button
                key={route.path}
                disabled={!navigation.ready}
                onClick={() => {
                  navigation.navigate(route.path);
                }}
              >
                {copy[`nav_${route.key}`]}
              </Button>
            ))}
          </Space>
        </Panel>
      </Panels>
    </Space>
  );
}

function QuantCard({
  q,
  ready,
  open,
}: {
  q: NonNullable<RiskSummary["quant"]>;
  ready: boolean;
  open: () => void;
}) {
  const { copy } = useCopy();
  const tag = (code: string | undefined) => (
    <Tag color={TAG_COLOR[code ?? ""] ?? "default"}>
      {tagText(copy, code ?? "neutral")}
    </Tag>
  );
  return (
    <Card
      size="small"
      title={copy.ov_quant}
      extra={
        <Space>
          {q.as_of && <span className="mm-muted">{q.as_of}</span>}
          <Button size="small" disabled={!ready} onClick={open}>
            {copy.ov_quantOpen}
          </Button>
        </Space>
      }
    >
      <Row gutter={[16, 12]}>
        <Col xs={24} md={12}>
          <div className="mm-muted">{copy.q_leadTitle}</div>
          <div>
            <b>{q.state}</b> {tag(q.state_code)}
          </div>
          <div className="mm-muted">
            {fill(copy.ov_quantStats, {
              b: fmt(q.breadth, 1),
              n: fmt(q.ndr, 1),
              stage: isNum(q.step_stage) ? q.step_stage : DASH,
              pos: isNum(q.step_pos) ? q.step_pos : DASH,
              cap: q.step_cap ? copy.ov_quantCap : "",
            })}
          </div>
        </Col>
        {q.micro_state && (
          <Col xs={24} md={12}>
            <div className="mm-muted">{copy.q_microTitle}</div>
            <div>
              <b>{q.micro_state}</b> {tag(q.micro_code)}
            </div>
            <div className="mm-muted">
              {fill(copy.ov_quantMicro, {
                pos: isNum(q.micro_pos) ? q.micro_pos : DASH,
              })}
            </div>
          </Col>
        )}
      </Row>
    </Card>
  );
}
