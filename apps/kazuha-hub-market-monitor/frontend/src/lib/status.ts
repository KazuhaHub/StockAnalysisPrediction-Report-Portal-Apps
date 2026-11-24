/**
 * antd Tag props for a status colour (docs/charts.md). A colour ending in
 * "-inverse" is the most severe level and renders solid (antd 6 deprecates
 * the "-inverse" presets in favour of variant="solid"); any other is the
 * default filled tag.
 */
export function tagProps(color: string): { color: string; variant?: "solid" } {
  return color.endsWith("-inverse")
    ? { color: color.slice(0, -"-inverse".length), variant: "solid" }
    : { color };
}

/** Sign of a number as it is shown with `digits` decimals: 0.03 at one
 * digit is a plain "0.0", so it takes no up/down colour. */
export function shown(
  x: number | null | undefined,
  digits: number,
): number | null {
  return typeof x === "number" && Number.isFinite(x)
    ? Number(x.toFixed(digits))
    : null;
}
