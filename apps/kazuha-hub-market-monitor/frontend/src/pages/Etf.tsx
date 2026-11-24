import { useMemo, useState } from "react";
import {
  Card,
  Descriptions,
  Empty,
  Segmented,
  Select,
  Space,
  Table,
  Tag,
} from "antd";
import type { TableColumnsType } from "antd";
import { ByteSearch } from "../components/ByteSearch";
import { Panel, Panels } from "../components/Panels";
import { Dashboard } from "../components/Dashboard";
import { EChart } from "../components/EChart";
import { KpiRow, type KpiItem } from "../components/Kpi";
import { RowTable } from "../components/RowTable";
import { Signed } from "../components/Signed";
import { useVisual } from "../components/useVisual";
import { useCopy, type Copy } from "../lib/copy";
import { useRowValues } from "../lib/hooks";
import { escapeHtml } from "../lib/html";
import { arr, fill, fmt, isNum, signed, DASH, type Num } from "../lib/format";

const DATA_DATE_KEYS = ["share", "nav", "amount", "index", "margin"] as const;

/** Names the source behind each "latest data date" key; unknown keys as is. */
function dataDateLabel(copy: Copy, key: string): string {
  return (DATA_DATE_KEYS as readonly string[]).includes(key)
    ? copy[`etf_date_${key}` as keyof Copy]
    : key;
}

type EtfSummary = {
  scope?: { universe?: string; n_codes?: Num; note?: string };
  current?: {
    last_date?: string;
    last_nf?: Num;
    /** Trading days the latest value spans; above 1 it is a merged value. */
    last_span?: Num;
    last_merged?: Num;
    last5?: Num;
    last20?: Num;
    ytd?: Num;
    idx_20d?: Num;
  };
  health?: {
    light?: string;
    label?: string;
    items?: { k: string; v?: string; note?: string; s?: Num }[];
  };
  runs_top?: { start: string; end: string; days?: Num; sum?: Num }[];
  series?: {
    dates?: string[];
    nf?: Num[];
    /** Trading days each value spans: above 1 the day has no share data of
     * its own and carries the whole change since the last observation. */
    nf_span?: Num[];
    nf_ma20?: Num[];
    idx?: Num[];
  };
  broad?: { dates?: string[]; cats?: string[]; series?: Record<string, Num[]> };
  data_health?: Record<string, string | null>;
};
export type EtfRow = {
  code: string;
  name?: string;
  cat?: string;
  cum_ytd?: Num;
  cum20?: Num;
};

export function EtfPage() {
  const { copy } = useCopy();
  return (
    <Dashboard<EtfSummary> module="etf" title={copy.etfTitle}>
      {(ctx) => <EtfBody {...ctx} />}
    </Dashboard>
  );
}

function EtfBody({
  summary: e,
  date,
  asOf,
  revision,
}: {
  summary: EtfSummary;
  date: string;
  asOf: string;
  revision: number;
}) {
  const { copy } = useCopy();
  const v = useVisual();
  const c = e.current ?? {};
  const s = e.series ?? {};
  const [range, setRange] = useState(120);
  const [search, setSearch] = useState("");
  const [cat, setCat] = useState<string>();
  const filters = useMemo(() => ({ cat }), [cat]);
  // The summary's category list misses some real values (for example
  // 国证2000), so the filter also offers the categories found in the rows.
  const rowCats = useRowValues("etf", date, "cat");
  const catOptions = useMemo(() => {
    const known = arr(e.broad?.cats);
    const extra = rowCats.filter((x) => !known.includes(x)).sort();
    return [...known, ...extra].map((x) => ({ value: x, label: x }));
  }, [e.broad?.cats, rowCats]);
  const lightColor = v.status[e.health?.light ?? ""];

  const flowOption = useMemo(() => {
    const dates = arr(s.dates);
    const a = Math.max(0, dates.length - range);
    const spans = arr(s.nf_span).slice(a);
    const merged = (i: number) => {
      const n = spans[i];
      return isNum(n) && n > 1 ? n : 0;
    };
    return {
      tooltip: {
        trigger: "axis",
        formatter: (
          params: {
            dataIndex: number;
            seriesIndex: number;
            axisValueLabel: string;
            marker: string;
            seriesName: string;
            value: unknown;
          }[],
        ) => {
          const list = Array.isArray(params) ? params : [params];
          if (!list.length) return "";
          const lines = list.map((p) => {
            const raw =
              p.value && typeof p.value === "object"
                ? (p.value as { value?: unknown }).value
                : p.value;
            const text = isNum(raw as Num)
              ? fmt(raw as Num, p.seriesIndex === 2 ? 2 : 1)
              : DASH;
            const n = p.seriesIndex === 0 ? merged(p.dataIndex) : 0;
            return `${p.marker}${escapeHtml(p.seriesName)}: ${text}${
              n ? ` (${escapeHtml(fill(copy.etf_merged, { n }))})` : ""
            }`;
          });
          return [escapeHtml(list[0].axisValueLabel), ...lines].join("<br/>");
        },
      },
      legend: { top: 0 },
      grid: { left: 50, right: 56, top: 36, bottom: 30 },
      xAxis: { type: "category", data: dates.slice(a) },
      yAxis: [
        { type: "value", name: copy.etf_flowAxis },
        {
          type: "value",
          name: copy.etf_indexAxis,
          scale: true,
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: copy.etf_flow,
          type: "bar",
          data: arr(s.nf)
            .slice(a)
            .map((x, i) => {
              const color = isNum(x) && x < 0 ? v.down : v.up;
              // A merged value is outlined, not filled: it is not one day's flow.
              return merged(i)
                ? {
                    value: x,
                    itemStyle: {
                      color: "transparent",
                      borderColor: color,
                      borderWidth: 1.5,
                      borderType: "dashed",
                    },
                  }
                : { value: x, itemStyle: { color } };
            }),
          // Bars are red or green by sign; the legend swatch is neutral.
          itemStyle: { color: v.series[4] },
        },
        {
          name: copy.etf_ma20,
          type: "line",
          showSymbol: false,
          data: arr(s.nf_ma20).slice(a),
          lineStyle: { width: 1, color: v.ma[20] },
          itemStyle: { color: v.ma[20] },
        },
        {
          name: copy.etf_index,
          type: "line",
          yAxisIndex: 1,
          showSymbol: false,
          // The index is the reference line: gray, on the right axis.
          data: arr(s.idx).slice(a),
          lineStyle: { width: 1.5, color: v.series[4] },
          itemStyle: { color: v.series[4] },
        },
      ],
    };
  }, [s, range, v, copy]);

  // Category totals come from the summary's per-category daily series.
  const catRows = useMemo(() => {
    const dates = arr(e.broad?.dates);
    const year = asOf.slice(0, 4);
    const firstYtd = dates.findIndex((d) => d.startsWith(year));
    return arr(e.broad?.cats)
      .map((name) => {
        const series = arr(e.broad?.series?.[name]);
        const sum = (from: number) =>
          series
            .slice(from)
            .reduce<number>((t, x) => t + (isNum(x) ? x : 0), 0);
        return {
          name,
          cum20: Math.round(sum(Math.max(0, series.length - 20))),
          ytd: Math.round(sum(firstYtd < 0 ? series.length : firstYtd)),
        };
      })
      .sort((a, b) => b.cum20 - a.cum20);
  }, [e.broad, asOf]);
  const catOption = useMemo(
    () => ({
      tooltip: { trigger: "axis" },
      legend: { top: 0 },
      grid: { left: 84, right: 20, top: 30, bottom: 20 },
      xAxis: { type: "value", name: copy.unit_yi },
      yAxis: { type: "category", data: catRows.map((x) => x.name).reverse() },
      series: [
        // Both are net flows: each bar is red for inflow, green for outflow.
        // The two windows differ by fill: last 20 days solid, year to date a
        // lighter fill with an outline (the legend shows the fill, in gray).
        {
          name: copy.etf_last20,
          type: "bar",
          data: catRows
            .map((x) => ({
              value: x.cum20,
              itemStyle: { color: x.cum20 < 0 ? v.down : v.up },
            }))
            .reverse(),
          itemStyle: { color: v.series[4] },
        },
        {
          name: copy.etf_ytd,
          type: "bar",
          data: catRows
            .map((x) => {
              const c = x.ytd < 0 ? v.down : v.up;
              return {
                value: x.ytd,
                itemStyle: {
                  color: c,
                  opacity: 0.35,
                  borderColor: c,
                  borderWidth: 1,
                },
              };
            })
            .reverse(),
          itemStyle: { color: v.series[4], opacity: 0.35 },
        },
      ],
    }),
    [catRows, v, copy],
  );

  const kpis: KpiItem[] = [
    {
      key: "nf",
      title: fill(copy.etf_latest, { date: c.last_date ?? DASH }),
      ...(isNum(c.last_merged) && isNum(c.last_span) && c.last_span > 1
        ? {
            // Not one day's flow: say how many trading days it covers.
            value: `${signed(c.last_merged, 1)} ${copy.unit_yi}`,
            color: v.sign(c.last_merged),
            note: fill(copy.etf_merged, { n: c.last_span }),
          }
        : {
            value: isNum(c.last_nf)
              ? `${signed(c.last_nf, 1)} ${copy.unit_yi}`
              : DASH,
            color: isNum(c.last_nf)
              ? c.last_nf >= 0
                ? v.up
                : v.down
              : undefined,
          }),
    },
    {
      key: "5",
      title: copy.etf_last5,
      value: isNum(c.last5) ? `${signed(c.last5, 0)} ${copy.unit_yi}` : DASH,
      color: v.sign(c.last5),
    },
    {
      key: "20",
      title: copy.etf_last20,
      value: isNum(c.last20) ? `${signed(c.last20, 0)} ${copy.unit_yi}` : DASH,
      color: v.sign(c.last20),
    },
    {
      key: "y",
      title: copy.etf_ytd,
      value: isNum(c.ytd) ? `${signed(c.ytd, 0)} ${copy.unit_yi}` : DASH,
      color: v.sign(c.ytd),
    },
    {
      key: "i",
      title: copy.etf_idx20,
      value: isNum(c.idx_20d) ? `${signed(c.idx_20d, 2)}%` : DASH,
      color: v.sign(c.idx_20d),
    },
    {
      key: "h",
      title: copy.etf_signal,
      value: e.health?.label ?? DASH,
      color: lightColor,
    },
  ];

  const sorted = (
    title: string,
    field: string,
    render: (x: Num) => React.ReactNode,
    width: number,
  ) => ({
    title,
    dataIndex: field,
    align: "right" as const,
    width,
    sorter: true,
    render,
  });
  const columns: TableColumnsType<EtfRow> = [
    { title: copy.col_code, dataIndex: "code", width: 84 },
    { title: copy.col_name, dataIndex: "name", width: 180 },
    {
      title: copy.etf_cat,
      dataIndex: "cat",
      width: 100,
      render: (x: string) => (x ? <Tag>{x}</Tag> : DASH),
    },
    sorted(
      `${copy.etf_last20} (${copy.unit_yi})`,
      "cum20",
      (x) => <Signed value={x} digits={1} />,
      130,
    ),
    sorted(
      `${copy.etf_ytd} (${copy.unit_yi})`,
      "cum_ytd",
      (x) => <Signed value={x} digits={1} />,
      130,
    ),
  ];
  const dh = e.data_health ?? {};

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      <KpiRow items={kpis} />
      <Card
        size="small"
        title={copy.etf_flowTitle}
        extra={
          <Segmented
            size="small"
            value={range}
            onChange={setRange}
            options={[
              { label: copy.range60, value: 60 },
              { label: copy.range120, value: 120 },
              { label: copy.rangeYear, value: 250 },
            ]}
          />
        }
      >
        {arr(s.dates).length ? (
          <>
            <EChart
              label={copy.etf_flowTitle}
              option={flowOption}
              height={340}
            />
            <div className="mm-muted">{copy.etf_flowNote}</div>
          </>
        ) : (
          <Empty description={copy.noData} />
        )}
      </Card>
      <Panels>
        <Panel kind="wide" title={copy.etf_catTitle}>
          {catRows.length ? (
            <EChart label={copy.etf_catTitle} option={catOption} height={330} />
          ) : (
            <Empty description={copy.noData} />
          )}
        </Panel>
        <Panel title={copy.etf_health}>
          {arr(e.health?.items).length === 0 && (
            <Empty description={copy.noData} />
          )}
          {arr(e.health?.items).map((item) => (
            <div key={item.k} className="mm-health">
              <div>
                <span>
                  {item.k}: <b>{item.v}</b>
                </span>
                <div className="mm-muted">{item.note}</div>
              </div>
              <Tag
                color={
                  // A signed reading: positive red, negative green.
                  isNum(item.s) && item.s < 0
                    ? "success"
                    : isNum(item.s) && item.s > 0
                      ? "error"
                      : "default"
                }
              >
                {isNum(item.s) && item.s < 0
                  ? copy.etf_negative
                  : isNum(item.s) && item.s > 0
                    ? copy.etf_positive
                    : copy.etf_neutral}
              </Tag>
            </div>
          ))}
        </Panel>
        <Panel title={copy.etf_runs}>
          <Table
            size="small"
            pagination={false}
            rowKey="start"
            dataSource={arr(e.runs_top).slice(0, 6)}
            columns={[
              { title: copy.etf_start, dataIndex: "start" },
              { title: copy.etf_end, dataIndex: "end" },
              { title: copy.etf_days, dataIndex: "days", align: "right" },
              {
                title: `${copy.etf_sum} (${copy.unit_yi})`,
                dataIndex: "sum",
                align: "right",
                render: (x: Num) => fmt(x, 0),
              },
            ]}
          />
          {e.scope && (
            <div className="mm-muted" style={{ marginTop: 8 }}>
              {fill(copy.etf_scope, {
                universe: e.scope.universe ?? DASH,
                n: e.scope.n_codes ?? DASH,
                note: e.scope.note ?? "",
              })}
            </div>
          )}
          {Object.keys(dh).length > 0 && (
            <Descriptions
              size="small"
              column={2}
              style={{ marginTop: 8 }}
              items={Object.entries(dh).map(([key, value]) => ({
                key,
                label: dataDateLabel(copy, key.replace(/_last$/, "")),
                children: value ?? DASH,
              }))}
            />
          )}
        </Panel>
        <Panel kind="detail" title={copy.etf_funds}>
          <Space wrap style={{ marginBottom: 12 }}>
            <ByteSearch
              placeholder={copy.searchPlaceholder}
              width={200}
              onSearch={setSearch}
            />
            <Select
              allowClear
              placeholder={copy.etf_cat}
              value={cat}
              onChange={setCat}
              style={{ width: 140 }}
              options={catOptions}
            />
          </Space>
          <RowTable<EtfRow>
            module="etf"
            date={date}
            revision={revision}
            columns={columns}
            defaultSort="cum20"
            q={search}
            filters={filters}
            scrollX={620}
          />
        </Panel>
      </Panels>
    </Space>
  );
}
