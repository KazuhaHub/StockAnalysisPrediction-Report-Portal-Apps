import { useMemo } from "react";
import { theme } from "antd";

/**
 * The app's chart colour rule, defined once here and used by every chart:
 *
 * 1. Signed values use A-share semantics: `up` (red) for rises, inflows and
 *    positive values, `down` (green) for falls, outflows and negative values.
 *    Red and green mean nothing else in a chart.
 * 2. Series identity (which line or category is which) takes `series`, in this
 *    order: primary blue, amber, purple, teal, gray, then magenta and geekblue.
 *    It never contains red or green. The level-7 tokens are used because the
 *    dark algorithm lightens them, so they keep contrast on both backgrounds.
 * 3. Secondary series (right axis, moving averages) are dashed or thinner in
 *    their series colour; thresholds and reference lines use `threshold`, a
 *    neutral dashed gray.
 * 4. Event markers use rule 1 when they mean bullish or bearish, otherwise a
 *    series colour.
 *
 * All values come from the host theme tokens, so light and dark both work.
 */
export function useVisual() {
  const { token } = theme.useToken();
  return useMemo(
    () => ({
      series: [
        token.colorPrimary,
        token.gold7,
        token.purple7,
        token.cyan7,
        token.colorTextTertiary,
        token.magenta7,
        token.geekblue7,
      ],
      // Neutral dashed gray for thresholds and reference lines (rule 3).
      threshold: {
        color: token.colorTextTertiary,
        type: "dashed" as const,
        width: 1,
      },
      primary: token.colorPrimary,
      // Colour of a signed number (rule 1): red above zero, green below,
      // undefined (the default text colour) at zero or when missing.
      sign: (x: number | null | undefined) =>
        typeof x !== "number" || !Number.isFinite(x) || x === 0
          ? undefined
          : x > 0
            ? token.colorError
            : token.colorSuccess,
      // Moving averages, as A-share terminals draw them: MA5 in the text
      // colour, MA10 amber, MA20 magenta/purple, MA60 teal; thin lines.
      ma: {
        5: token.colorText,
        10: token.gold7,
        20: token.magenta7,
        60: token.cyan7,
        120: token.geekblue7,
        200: token.colorTextTertiary,
      } as Record<number, string>,
      // A status (a signal light, a state) is not a sign, so never red or
      // green: gray for "off/failed", amber for "watch", blue for "usable".
      status: {
        red: token.colorTextSecondary,
        amber: token.gold7,
        green: token.colorPrimary,
      } as Record<string, string>,
      // The most severe warning (margin 高危/临界): a strong orange, still not red.
      alert: token.orange7,
      statusTag: {
        red: "default",
        amber: "warning",
        green: "processing",
      } as Record<string, string>,
      up: token.colorError,
      down: token.colorSuccess,
      warning: token.colorWarning,
      danger: token.colorError,
      success: token.colorSuccess,
      info: token.colorInfo,
      // Named series colours, the same values as series[1..3].
      orange: token.gold7,
      purple: token.purple7,
      cyan: token.cyan7,
      text: token.colorTextSecondary,
      textStrong: token.colorText,
      textMuted: token.colorTextQuaternary,
      border: token.colorBorderSecondary,
      borderStrong: token.colorBorder,
      tooltipBg: token.colorBgElevated,
      zoomFill: token.colorPrimaryBgHover,
      surface: token.colorBgContainer,
      successBg: token.colorSuccessBg,
      errorBg: token.colorErrorBg,
      fillQuaternary: token.colorFillQuaternary,
    }),
    [token],
  );
}
export type Visual = ReturnType<typeof useVisual>;
