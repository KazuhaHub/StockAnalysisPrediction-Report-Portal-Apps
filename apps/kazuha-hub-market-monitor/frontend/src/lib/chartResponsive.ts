/**
 * The one responsive transform every chart option goes through (EChart.tsx).
 *
 * Below COMPACT_WIDTH, measured on the chart's own container (a half-width
 * panel on a desktop can be as narrow as a phone), an option is rewritten so
 * that on a phone:
 *
 * - the legend is one scrolling row of its own, and the grid starts below it
 *   (never over the plot, never over a top axis name);
 * - axis labels thin out instead of colliding, ISO dates become MM-DD, long
 *   category names wrap inside a smaller left margin;
 * - the two axes of a dual-axis chart keep readable margins, and their names
 *   hang inward from the plot's edges so neither runs off the chart;
 * - the tooltip stays inside the chart;
 * - an `inside` zoom, which turns every swipe on the chart into a pan and traps
 *   the page's own scroll, gives way to the slider.
 *
 * Only layout is touched. No colour is read, written or removed here: the
 * colour rules live in useVisual.ts and docs/charts.md. The author's own
 * explicit choices (an axis formatter, an interval, a tooltip option) win.
 * The function never mutates its input and returns it unchanged when the
 * container is wide or not measured yet.
 */
type Obj = Record<string, any>;

export const COMPACT_WIDTH = 520;
/** A reading height on a phone for a chart that was drawn for a desktop. */
export const COMPACT_MIN_HEIGHT = 280;
/** Height of one scrolling legend row, with its padding. */
const LEGEND_ROW = 34;
/** Room above a grid for a value axis' name. */
const AXIS_NAME_ROW = 18;
/** Room below a grid for its category labels. */
const LABEL_ROW = 30;
const MAX_MARGIN = 52;
const MIN_AXIS_MARGIN = 40;
const DATE = /^\d{4}-(\d{2}-\d{2})$/;

export function isCompact(width: number): boolean {
  return width > 0 && width < COMPACT_WIDTH;
}

/** "2026-11-24" as "11-24"; anything else is left as it is. */
export function shortDate(value: unknown): string {
  return typeof value === "string" ? value.replace(DATE, "$1") : String(value);
}

const asList = (x: unknown): Obj[] =>
  x === undefined || x === null ? [] : Array.isArray(x) ? x : [x as Obj];

/** Applies `f` to an option that may be one object or an array of them. */
function each<T>(x: T | T[] | undefined, f: (o: T, i: number) => T) {
  if (x === undefined) return undefined;
  return Array.isArray(x) ? x.map(f) : f(x, 0);
}

const percent = (x: unknown): number | null => {
  if (typeof x !== "string") return null;
  const m = /^(\d+(?:\.\d+)?)%$/.exec(x);
  return m ? Number(m[1]) : null;
};

function isDates(axis: Obj): boolean {
  const first = Array.isArray(axis.data) ? axis.data[0] : undefined;
  return typeof first === "string" && DATE.test(first);
}

function categoryXAxis(axis: Obj): Obj {
  if (axis.type !== undefined && axis.type !== "category") return axis;
  const label = axis.axisLabel ?? {};
  return {
    ...axis,
    axisLabel: {
      hideOverlap: true,
      fontSize: 10,
      ...(isDates(axis) ? { formatter: shortDate } : {}),
      ...label,
    },
  };
}

function valueAxis(axis: Obj, splits: number): Obj {
  return {
    ...axis,
    splitNumber: axis.splitNumber ?? splits,
    axisLabel: { fontSize: 10, hideOverlap: true, ...(axis.axisLabel ?? {}) },
    ...(axis.name === undefined
      ? {}
      : {
          nameTextStyle: { fontSize: 10, ...(axis.nameTextStyle ?? {}) },
        }),
  };
}

function legendOf(legend: Obj): Obj {
  if (legend.show === false) return legend;
  const moved =
    legend.orient === "vertical"
      ? { orient: "horizontal", left: "center", right: undefined }
      : {};
  return {
    type: "scroll",
    itemGap: 8,
    pageIconSize: 11,
    ...legend,
    ...moved,
    textStyle: { fontSize: 11, ...(legend.textStyle ?? {}) },
  };
}

const legendsOf = (option: Obj) =>
  asList(option.legend).filter((l) => l.show !== false);
const atBottom = (legend: Obj) =>
  legend.bottom !== undefined && legend.top === undefined;

function responsiveGrid(
  grid: Obj,
  option: Obj,
  width: number,
  yNamed: boolean,
  yCategory: boolean,
  dual: boolean,
): Obj {
  const next: Obj = { ...grid };
  const legends = legendsOf(option);
  const top = legends.some((l) => !atBottom(l));
  const bottom = legends.some(atBottom);
  if (top) {
    const room = LEGEND_ROW + (yNamed ? AXIS_NAME_ROW : 0);
    if (typeof next.top === "number") next.top = Math.max(next.top, room);
    else if (next.top === undefined) next.top = room;
  }
  if (bottom && typeof next.bottom === "number")
    next.bottom = Math.max(next.bottom, LABEL_ROW + LEGEND_ROW);
  if (yCategory) {
    // Long category names wrap inside a smaller margin instead of eating the plot.
    if (typeof next.left === "number")
      next.left = Math.min(next.left, Math.round(width * 0.28));
  } else {
    if (typeof next.left === "number")
      next.left = Math.max(MIN_AXIS_MARGIN, Math.min(next.left, MAX_MARGIN));
    if (typeof next.right === "number")
      next.right = dual
        ? Math.max(MIN_AXIS_MARGIN, Math.min(next.right, MAX_MARGIN))
        : Math.min(next.right, MAX_MARGIN);
  }
  return next;
}

/** Rewrites `option` for a narrow container; see the file comment. */
export function responsiveOption<T extends Obj>(option: T, width: number): T {
  if (!isCompact(width)) return option;
  const out: Obj = { ...option };

  if (option.legend !== undefined) out.legend = each(option.legend, legendOf);

  const xs = asList(option.xAxis);
  const ys = asList(option.yAxis);
  const yCategory = ys.length > 0 && ys.every((a) => a.type === "category");
  const dual = ys.length > 1;
  if (option.xAxis !== undefined)
    out.xAxis = each(option.xAxis, (axis) =>
      axis.type === "value" ? valueAxis(axis, 3) : categoryXAxis(axis as Obj),
    );
  if (option.yAxis !== undefined)
    out.yAxis = each(option.yAxis, (axis, i) => {
      if (axis.type === "category") {
        const left = (option.grid as Obj | undefined)?.left;
        const room =
          typeof left === "number"
            ? Math.min(left, Math.round(width * 0.28))
            : 0;
        return {
          ...axis,
          axisLabel: {
            fontSize: 10,
            ...(room > 0 ? { width: room - 8, overflow: "break" } : {}),
            ...(axis.axisLabel ?? {}),
          },
        };
      }
      const next = valueAxis(axis, 4);
      if (!dual) return next;
      return {
        ...next,
        // One set of grid lines is enough; the second axis only has its labels.
        ...(i > 0 && axis.splitLine === undefined
          ? { splitLine: { show: false } }
          : {}),
        ...(axis.name !== undefined
          ? {
              nameTextStyle: {
                align: i === 0 ? "left" : "right",
                ...next.nameTextStyle,
              },
            }
          : {}),
      };
    });

  if (option.grid !== undefined) {
    const yNamed = ys.some(
      (a) => a.type !== "category" && a.name !== undefined,
    );
    out.grid = each(option.grid, (grid) =>
      responsiveGrid(grid, option, width, yNamed, yCategory, dual),
    );
  } else if (legendsOf(option).length && xs.length) {
    // A chart with a legend and the default grid still gets room for it.
    out.grid = { top: LEGEND_ROW + 26 };
  }

  if (option.tooltip !== undefined)
    out.tooltip = each(option.tooltip, (t) => ({ confine: true, ...t }));

  if (option.dataZoom !== undefined) {
    const kept = asList(option.dataZoom).filter((z) => z.type !== "inside");
    if (kept.length)
      out.dataZoom = Array.isArray(option.dataZoom) ? kept : kept[0];
    else delete out.dataZoom;
  }

  if (option.radar !== undefined)
    out.radar = each(option.radar, (r) => {
      const wanted = percent(r.radius);
      return {
        ...r,
        ...(wanted !== null && wanted > 56 ? { radius: "56%" } : {}),
        axisName: { fontSize: 10, ...(r.axisName ?? {}) },
      };
    });

  if (Array.isArray(option.series))
    out.series = option.series.map((s: Obj) =>
      s.type === "pie"
        ? {
            ...s,
            label: { fontSize: 10, ...(s.label ?? {}) },
            labelLine: { length: 8, length2: 6, ...(s.labelLine ?? {}) },
            labelLayout: { hideOverlap: true, ...(s.labelLayout ?? {}) },
          }
        : s,
    );

  return out as T;
}

/**
 * The height a chart takes. A chart drawn for a desktop is lifted to a
 * reading height on a phone; a sparkline (anything under 200px) is left alone.
 */
export function responsiveHeight(height: number, width: number): number {
  return isCompact(width) && height >= 200
    ? Math.max(height, COMPACT_MIN_HEIGHT)
    : height;
}
