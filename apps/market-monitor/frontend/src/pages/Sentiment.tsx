import { useMemo } from "react";
import { Alert, Card, Col, Empty, Progress, Row, Space, Table } from "antd";
import { Dashboard } from "../components/Dashboard";
import { EChart } from "../components/EChart";
import { KpiRow, type KpiItem } from "../components/Kpi";
import { useVisual } from "../components/useVisual";
import { useCopy } from "../lib/copy";
import { arr, fill, fmt, isNum, signed, DASH, type Num } from "../lib/format";
import { escapeHtml } from "../lib/html";

type Dim = {
  k: string;
  desc?: string;
  v?: Num;
  d1?: Num;
  d5?: Num;
  d20?: Num;
  verdict?: string;
};
type SentimentSummary = {
  asof?: string;
  headline?: string;
  dims?: Dim[];
  disp?: { v?: Num; rank?: Num };
  grid?: {
    x?: string[];
    y?: string[];
    cells?: { v?: Num; n?: Num; cur?: boolean }[][];
  };
  signal?: {
    active?: boolean;
    trigger?: string;
    days?: Num;
    ret_since?: Num;
    hist_n?: Num;
    hist_med20?: Num;
    hist_win20?: Num;
    path?: Num[];
    cur_path?: Num[];
  };
  extreme?: { name: string; v?: string; pct?: Num }[];
  alerts?: { level?: string; title?: string; body?: string }[];
  traj?: { dates?: string[]; series?: Record<string, Num[]> };
  conclusion?: { v?: Num; note?: string };
};

/**
 * Removes only the emphasis and line-break markup the pipeline emits. Any
 * other "<" is data (for example "breadth <10% ... >35%") and stays.
 */
export const stripTags = (text: string | undefined) =>
  (text ?? "").replace(/<\/?b>/gi, "").replace(/<br\s*\/?>/gi, " ");

/** Symmetric colour range around 0 from the grid values, with a fallback. */
export function heatRange(
  cells: { v?: Num }[][] | undefined,
  fallback = 3,
): { min: number; max: number } {
  let peak = 0;
  for (const row of arr(cells))
    for (const cell of arr(row))
      if (isNum(cell?.v)) peak = Math.max(peak, Math.abs(cell.v));
  const bound = peak > 0 ? Math.ceil(peak * 2) / 2 : fallback;
  return { min: -bound, max: bound };
}
const alertType = (level?: string) =>
  (
    ({
      red: "error",
      amber: "warning",
      green: "success",
      gray: "info",
    }) as const
  )[level as "red"] ?? "info";

export function SentimentPage() {
  const { copy } = useCopy();
  return (
    <Dashboard<SentimentSummary> module="sentiment" title={copy.sentimentTitle}>
      {({ summary }) => <SentimentBody s={summary} />}
    </Dashboard>
  );
}

function SentimentBody({ s }: { s: SentimentSummary }) {
  const { copy } = useCopy();
  const v = useVisual();
  const sig = s.signal;
  const dims = arr(s.dims);
  const traj = s.traj;
  const trajOption = useMemo(
    () => ({
      tooltip: { trigger: "axis" },
      legend: { top: 0 },
      grid: { left: 40, right: 20, top: 36, bottom: 50 },
      xAxis: { type: "category", data: arr(traj?.dates) },
      yAxis: { type: "value", min: 0, max: 100 },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }],
      series: Object.entries(traj?.series ?? {}).map(([name, data]) => ({
        name,
        type: "line",
        showSymbol: false,
        data,
        lineStyle: { width: name === "广度" ? 3 : 1.2 },
      })),
    }),
    [traj],
  );
  const grid = s.grid;
  const gridOption = useMemo(() => {
    if (!grid?.cells?.length) return null;
    const data: { value: [number, number, Num]; n: Num; cur?: boolean }[] = [];
    grid.cells.forEach((row, y) =>
      row.forEach((c, x) =>
        data.push({ value: [x, y, c?.v ?? null], n: c?.n, cur: c?.cur }),
      ),
    );
    return {
      tooltip: {
        formatter: (p: { value: [number, number, Num]; data: { n: Num } }) =>
          `${escapeHtml(arr(grid.y)[p.value[1]])} × ${escapeHtml(arr(grid.x)[p.value[0]])}<br/>${copy.sent_gridMedian} ${isNum(p.value[2]) ? `${p.value[2]}%` : copy.sent_noSample}<br/>${fill(copy.sent_sample, { n: p.data.n ?? DASH })}`,
      },
      grid: { left: 80, right: 20, top: 10, bottom: 30 },
      xAxis: { type: "category", data: arr(grid.x) },
      yAxis: { type: "category", data: arr(grid.y) },
      visualMap: {
        ...heatRange(grid.cells),
        show: false,
        inRange: { color: [v.success, v.surface, v.danger] },
        outOfRange: { color: v.fillQuaternary },
      },
      series: [
        {
          type: "heatmap",
          data: data.map((d) => ({
            ...d,
            value:
              d.value[2] === null ? [d.value[0], d.value[1], "-"] : d.value,
          })),
          label: {
            show: true,
            fontWeight: 600,
            color: v.textStrong,
            formatter: (p: {
              value: [number, number, Num | "-"];
              data: { cur?: boolean };
            }) =>
              `${isNum(p.value[2]) ? `${p.value[2]}%` : DASH}${p.data.cur ? `\n◆ ${copy.sent_current}` : ""}`,
          },
          itemStyle: { borderColor: v.surface, borderWidth: 2 },
        },
      ],
    };
  }, [grid, v, copy]);
  const sigOption = useMemo(() => {
    if (!sig?.path?.length && !sig?.cur_path?.length) return null;
    const n = Math.max(arr(sig?.path).length, arr(sig?.cur_path).length);
    return {
      tooltip: { trigger: "axis" },
      legend: { top: 0 },
      grid: { left: 40, right: 20, top: 36, bottom: 30 },
      xAxis: {
        type: "category",
        data: Array.from({ length: n }, (_, i) => `T+${i}`),
      },
      yAxis: { type: "value", name: "%" },
      series: [
        {
          name: copy.sent_histPath,
          type: "line",
          showSymbol: false,
          data: arr(sig?.path),
          lineStyle: { type: "dashed" },
        },
        {
          name: copy.sent_curPath,
          type: "line",
          showSymbol: false,
          data: arr(sig?.cur_path),
          lineStyle: { width: 3 },
        },
      ],
    };
  }, [sig, copy]);

  const kpis: KpiItem[] = [
    {
      key: "c",
      title: copy.sent_conclusion,
      value: fmt(s.conclusion?.v, 1),
      note: s.conclusion?.note,
    },
    {
      key: "d",
      title: fill(copy.sent_disp, { rank: fmt(s.disp?.rank, 0) }),
      value: isNum(s.disp?.v) ? `${fmt(s.disp.v, 0)} pp` : DASH,
    },
    ...(sig
      ? [
          {
            key: "s",
            title: fill(copy.sent_signal, { date: sig.trigger ?? DASH }),
            value: isNum(sig.days)
              ? fill(copy.sent_dayN, { n: sig.days })
              : DASH,
          },
          {
            key: "r",
            title: copy.sent_retSince,
            value: isNum(sig.ret_since) ? `${signed(sig.ret_since, 2)}%` : DASH,
            color: isNum(sig.ret_since)
              ? sig.ret_since < 0
                ? v.down
                : v.up
              : undefined,
          },
        ]
      : []),
  ];
  const barColor = (value: Num) =>
    isNum(value) && value < 20
      ? v.primary
      : isNum(value) && value > 80
        ? v.danger
        : v.text;

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      {s.headline && (
        <Alert
          type="warning"
          showIcon
          title={`${copy.sent_reading} · ${s.asof ?? ""}`}
          description={s.headline}
        />
      )}
      <KpiRow items={kpis} cols={{ xs: 12, md: 6 }} />
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={10}>
          <Card size="small" title={copy.sent_dims} style={{ height: "100%" }}>
            {dims.length === 0 && <Empty description={copy.noData} />}
            {dims.map((d) => (
              <div key={d.k} style={{ marginBottom: 12 }}>
                <div className="mm-between">
                  <b>{d.k}</b>
                  <span className="mm-muted">
                    {fill(copy.sent_history, {
                      d1: fmt(d.d1, 0),
                      d5: fmt(d.d5, 0),
                      d20: fmt(d.d20, 0),
                    })}
                  </span>
                </div>
                <Progress
                  percent={isNum(d.v) ? d.v : 0}
                  format={() => fmt(d.v, 1)}
                  strokeColor={barColor(d.v)}
                />
                <div className="mm-muted">
                  {[d.desc, d.verdict].filter(Boolean).join(" · ")}
                </div>
              </div>
            ))}
          </Card>
        </Col>
        <Col xs={24} lg={14}>
          <Card size="small" title={copy.sent_grid} style={{ height: "100%" }}>
            {gridOption ? (
              <EChart label={copy.sent_grid} option={gridOption} height={300} />
            ) : (
              <Empty description={copy.noData} />
            )}
            <div className="mm-muted">{copy.sent_gridNote}</div>
          </Card>
        </Col>
      </Row>
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card
            size="small"
            title={copy.sent_process}
            extra={
              sig && (
                <span className="mm-muted">
                  {fill(copy.sent_processNote, {
                    n: sig.hist_n ?? DASH,
                    med: signed(sig.hist_med20, 2),
                    win: fmt(sig.hist_win20, 0),
                  })}
                </span>
              )
            }
          >
            {sigOption ? (
              <EChart
                label={copy.sent_process}
                option={sigOption}
                height={300}
              />
            ) : (
              <Empty description={copy.noData} />
            )}
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card size="small" title={copy.sent_alerts}>
            {arr(s.alerts).length === 0 && <Empty description={copy.noData} />}
            {arr(s.alerts).map((a, i) => (
              <Alert
                key={i}
                style={{ marginBottom: 8 }}
                type={alertType(a.level)}
                title={a.title}
                description={stripTags(a.body)}
              />
            ))}
          </Card>
        </Col>
      </Row>
      <Card size="small" title={copy.sent_trajectory}>
        {arr(traj?.dates).length ? (
          <EChart
            label={copy.sent_trajectory}
            option={trajOption}
            height={340}
          />
        ) : (
          <Empty description={copy.noData} />
        )}
      </Card>
      <Card size="small" title={copy.sent_extreme}>
        <Table
          size="small"
          pagination={false}
          rowKey="name"
          dataSource={arr(s.extreme)}
          columns={[
            { title: copy.sent_indicator, dataIndex: "name" },
            { title: copy.sent_value, dataIndex: "v", align: "right" },
            {
              title: copy.sent_pct3y,
              dataIndex: "pct",
              width: "45%",
              render: (x: Num) => (
                <Progress
                  percent={isNum(x) ? x : 0}
                  size="small"
                  format={() => fmt(x, 0)}
                  strokeColor={
                    isNum(x) && (x > 85 || x < 15) ? v.danger : undefined
                  }
                />
              ),
            },
          ]}
        />
      </Card>
    </Space>
  );
}
