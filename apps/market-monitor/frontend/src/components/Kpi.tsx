import { useMemo, type ReactNode } from "react";
import { Card, Col, Row, Statistic, Tag } from "antd";
import { EChart } from "./EChart";
import type { Num } from "../lib/format";
import { isNum } from "../lib/format";

export function Spark({
  data,
  color,
  label,
}: {
  data: Num[];
  color: string;
  label: string;
}) {
  const values = useMemo(() => data.filter(isNum), [data]);
  const option = useMemo(
    () => ({
      grid: { left: 0, right: 0, top: 4, bottom: 0 },
      xAxis: { type: "category", show: false, data: values.map((_, i) => i) },
      yAxis: { type: "value", show: false, scale: true },
      tooltip: { show: false },
      series: [
        {
          type: "line",
          data: values,
          showSymbol: false,
          lineStyle: { width: 1.5, color },
          areaStyle: { opacity: 0.12, color },
        },
      ],
    }),
    [values, color],
  );
  if (values.length < 2) return <div className="mm-spark" />;
  return <EChart label={label} height={44} option={option} />;
}

export type KpiItem = {
  key: string;
  title: string;
  value: string;
  color?: string;
  note?: ReactNode;
  tag?: { text: string; color: string };
  spark?: { data: Num[]; color: string };
};

export function KpiRow({
  items,
  cols = { xs: 12, md: 8, xl: 4 },
}: {
  items: KpiItem[];
  cols?: {
    xs: number;
    sm?: number;
    md?: number;
    lg?: number;
    xl?: number;
    xxl?: number;
  };
}) {
  return (
    <Row gutter={[12, 12]}>
      {items.map((item) => (
        <Col key={item.key} {...cols}>
          <Card size="small" className="mm-kpi" style={{ height: "100%" }}>
            <Statistic
              title={item.title}
              value={item.value}
              styles={
                item.color ? { content: { color: item.color } } : undefined
              }
            />
            {item.spark && (
              <Spark
                data={item.spark.data}
                color={item.spark.color}
                label={item.title}
              />
            )}
            {(item.tag || item.note) && (
              <div>
                {item.tag && <Tag color={item.tag.color}>{item.tag.text}</Tag>}
                {item.note && <span className="mm-muted">{item.note}</span>}
              </div>
            )}
          </Card>
        </Col>
      ))}
    </Row>
  );
}
