import { locales, type Locale } from "./copy";

export type Num = number | null | undefined;

export const isNum = (v: unknown): v is number =>
  typeof v === "number" && Number.isFinite(v);

export const DASH = "—";

export function fmt(v: Num, digits = 1): string {
  return isNum(v) ? v.toFixed(digits) : DASH;
}

export function signed(v: Num, digits = 1): string {
  return isNum(v) ? (v > 0 ? "+" : "") + v.toFixed(digits) : DASH;
}

export function pct(v: Num, digits = 1): string {
  return isNum(v) ? (v * 100).toFixed(digits) + "%" : DASH;
}

/**
 * Amounts in the data are in units of 100 million CNY. The unit words come from
 * the locale copy: Chinese groups by 10^4 (亿, 万亿), English by 10^3 (bn, tn).
 */
export function formatYi(v: Num, locale: Locale): string {
  if (!isNum(v)) return DASH;
  const copy = locales[locale];
  const large = Math.abs(v) >= 10000;
  if (locale === "en-US")
    return fill(large ? copy.amt_large : copy.amt_small, {
      n: large ? (v / 10000).toFixed(2) : (v / 10).toFixed(1),
    });
  return fill(large ? copy.amt_large : copy.amt_small, {
    n: large ? (v / 10000).toFixed(2) : v.toFixed(0),
  });
}

/** UTF-8 length of a string, the unit of the backend's 64-byte query limit. */
export function utf8Length(text: string): number {
  return new TextEncoder().encode(text).length;
}

export const MAX_QUERY_BYTES = 64;

export function splitTags(value: unknown): string[] {
  return typeof value === "string"
    ? value.split(/[|,，\s]+/).filter(Boolean)
    : [];
}

export const arr = <T>(v: T[] | null | undefined): T[] =>
  Array.isArray(v) ? v : [];

export function fill(
  template: string,
  vars: Record<string, string | number>,
): string {
  return template.replace(/\{(\w+)\}/g, (_, key: string) =>
    key in vars ? String(vars[key]) : "",
  );
}

/** Rolling sum over a window, null until the window is full. */
export function rollingSum(values: Num[], window: number): Num[] {
  return values.map((_, i) => {
    if (i < window - 1) return null;
    let sum = 0;
    for (const v of values.slice(i - window + 1, i + 1))
      sum += isNum(v) ? v : 0;
    return Math.round(sum);
  });
}

export function lastNumber(values: Num[] | null | undefined): Num {
  const list = arr(values);
  for (let i = list.length - 1; i >= 0; i--) if (isNum(list[i])) return list[i];
  return null;
}
