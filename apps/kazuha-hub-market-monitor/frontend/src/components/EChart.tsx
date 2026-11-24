import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts/core";
import {
  BarChart,
  HeatmapChart,
  LineChart,
  PieChart,
  RadarChart,
  ScatterChart,
} from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  RadarComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { responsiveHeight, responsiveOption } from "../lib/chartResponsive";
import { useVisual, type Visual } from "./useVisual";

echarts.use([
  BarChart,
  HeatmapChart,
  LineChart,
  PieChart,
  RadarChart,
  ScatterChart,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  RadarComponent,
  TooltipComponent,
  VisualMapComponent,
  CanvasRenderer,
]);

export type ChartOption = echarts.EChartsCoreOption;

function chartTheme(v: Visual) {
  const axis = {
    axisLine: { lineStyle: { color: v.border } },
    axisTick: { lineStyle: { color: v.border } },
    axisLabel: { color: v.text },
    nameTextStyle: { color: v.text },
    splitLine: { lineStyle: { color: v.border } },
  };
  // Data labels use the text colour with no outline: ECharts' default white
  // outline shows as a halo on a dark background.
  const label = { label: { color: v.text, textBorderWidth: 0 } };
  return {
    color: v.series,
    bar: label,
    pie: label,
    line: label,
    scatter: label,
    heatmap: label,
    backgroundColor: "transparent",
    textStyle: { color: v.text },
    categoryAxis: axis,
    valueAxis: axis,
    legend: { textStyle: { color: v.text }, inactiveColor: v.textMuted },
    tooltip: {
      backgroundColor: v.tooltipBg,
      borderColor: v.borderStrong,
      textStyle: { color: v.textStrong },
      extraCssText: "box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25);",
    },
    dataZoom: {
      backgroundColor: v.fillQuaternary,
      borderColor: v.border,
      fillerColor: v.zoomFill,
      dataBackground: {
        lineStyle: { color: v.textMuted },
        areaStyle: { color: v.textMuted, opacity: 0.2 },
      },
      selectedDataBackground: {
        lineStyle: { color: v.primary },
        areaStyle: { color: v.primary, opacity: 0.3 },
      },
      handleStyle: {
        color: v.surface,
        borderColor: v.primary,
        borderWidth: 1,
      },
      moveHandleStyle: { color: v.primary, opacity: 0.5 },
      textStyle: { color: v.text },
    },
    radar: {
      axisName: { color: v.text },
      splitLine: { lineStyle: { color: v.border } },
      axisLine: { lineStyle: { color: v.border } },
      splitArea: { show: false },
    },
  };
}

type Props = {
  option: ChartOption;
  height?: number;
  label: string;
};

/**
 * A canvas ECharts instance themed from the host tokens. Every option goes
 * through the one responsive transform (lib/chartResponsive.ts), driven by the
 * container's own measured width, and a phone gets a readable height.
 */
export function EChart({ option, height = 300, label }: Props) {
  const visual = useVisual();
  const host = useRef<HTMLDivElement>(null);
  const themed = useMemo(() => chartTheme(visual), [visual]);
  const chart = useRef<echarts.ECharts | null>(null);
  // 0 until measured: an unmeasured chart is drawn as given.
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const element = host.current;
    if (!element) return;
    setWidth(Math.round(element.clientWidth));
    const observer = new ResizeObserver(() =>
      setWidth(Math.round(element.clientWidth)),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  // The instance is created once per mount and theme change; option changes
  // below replace its option without re-creating it.
  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const instance = echarts.init(element, themed, { renderer: "canvas" });
    chart.current = instance;
    // Development only (compiled out of the package): the layout check reads
    // the legend and plot rectangles from the instance.
    if (import.meta.env.DEV)
      (element as HTMLElement & { __mmChart?: unknown }).__mmChart = instance;
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(element);
    return () => {
      observer.disconnect();
      instance.dispose();
      chart.current = null;
    };
  }, [themed]);
  const shown = useMemo(() => responsiveOption(option, width), [option, width]);
  useEffect(() => {
    chart.current?.setOption(shown, { notMerge: true });
  }, [shown, themed]);
  return (
    <div
      ref={host}
      role="img"
      aria-label={label}
      className="mm-chart"
      style={{ height: responsiveHeight(height, width) }}
    />
  );
}
