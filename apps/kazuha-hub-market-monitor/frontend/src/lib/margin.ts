import { isNum, type Num } from "./format";

/**
 * Distribution of the margin crowding ratio (percent) as the pipeline writes it
 * into the margin overview: bin i covers [i * width, (i + 1) * width) and the
 * last bin is open-ended. `median` is the ratio median, when known.
 */
export type RatioHist = { width: number; counts: number[]; median: Num };

/** The histogram when `raw` is well formed, else null (the chart falls back). */
export function parseRatioHist(raw: unknown): RatioHist | null {
  if (typeof raw !== "object" || raw === null) return null;
  const { width, counts, median } = raw as Record<string, unknown>;
  if (!isNum(width) || width <= 0) return null;
  if (!Array.isArray(counts) || counts.length === 0) return null;
  if (!counts.every((n) => isNum(n) && n >= 0)) return null;
  return {
    width,
    counts: counts as number[],
    median: isNum(median) ? median : null,
  };
}

/** Bins from this ratio up are drawn in the danger colour. */
export const HIST_DANGER_FROM = 8;

export function ratioHistBars(h: RatioHist) {
  return h.counts.map((value, i) => {
    const start = i * h.width;
    // The last bin is open-ended: it holds everything from its start up.
    const open = i === h.counts.length - 1;
    return {
      label: open ? `≥${start.toFixed(1)}` : start.toFixed(1),
      start,
      value,
      danger: start >= HIST_DANGER_FROM,
    };
  });
}

/** The bin label a ratio falls in (the last bin takes everything above). */
export function histBinLabel(h: RatioHist, ratio: number): string {
  const i = Math.min(
    h.counts.length - 1,
    Math.max(0, Math.floor(ratio / h.width)),
  );
  return ratioHistBars(h)[i].label;
}

/**
 * Passive-selling mechanisms the backend can filter on (`mechanism=<name>`).
 * The set is closed on both sides; display text is `mech_<name>` in the copy.
 */
export const MECHANISMS = ["res2", "pledge", "unlock", "cb", "block"] as const;
export type Mechanism = (typeof MECHANISMS)[number];

/** Progress-bar tone of the forward-looking fragility score. */
export function fragTone(value: Num): "danger" | "warning" | undefined {
  if (!isNum(value)) return undefined;
  return value > 90 ? "danger" : value > 70 ? "warning" : undefined;
}
