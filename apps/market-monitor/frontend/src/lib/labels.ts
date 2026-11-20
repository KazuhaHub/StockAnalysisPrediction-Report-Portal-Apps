import type { Copy } from "./copy";

/**
 * The pipeline emits these categorical values in Chinese and the backend
 * filters on them verbatim, so the values stay as they are and only their
 * display text goes through the locale copy.
 */
const KEYS = {
  临界: "val_critical",
  潜伏: "val_latent",
  已去杠杆: "val_flushed",
  安全: "val_safe",
  高危: "val_high",
  关注: "val_watch",
  正常: "val_normal",
  价跌加杠杆: "val_tagFall",
  占比畸高: "val_tagShare",
  涨中撤杠杆: "val_tagRise",
  杠杆沉淀厚: "val_tagThick",
  杠杆定价: "val_tagPriced",
  高位加杠杆: "val_tagHigh",
  显著低估: "val_lblVeryLow",
  低估: "val_lblLow",
  合理: "val_lblFair",
  高估: "val_lblHigh",
  显著高估: "val_lblVeryHigh",
  分歧过大: "val_lblSplit",
  单一方法参考: "val_lblSingle",
  数据不足: "val_lblNoData",
  便宜好公司: "val_quadGood",
  优质但贵: "val_quadPricey",
  价值陷阱: "val_quadTrap",
  又贵又差: "val_quadBad",
  未分类: "val_quadNone",
  金融: "val_profFin",
  均衡: "val_profBalanced",
  周期: "val_profCyclical",
  成长: "val_profGrowth",
  红利: "val_profDividend",
} as const satisfies Record<string, keyof Copy>;

/** Display text of a categorical data value; unknown values display as is. */
export function valueLabel(copy: Copy, value: string): string {
  return Object.hasOwn(KEYS, value)
    ? copy[KEYS[value as keyof typeof KEYS]]
    : value;
}

/** Select options that send the data value and show its localised label. */
export function valueOptions(copy: Copy, values: readonly string[]) {
  return values.map((value) => ({ value, label: valueLabel(copy, value) }));
}
