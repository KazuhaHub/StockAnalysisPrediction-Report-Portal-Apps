import { useMemo } from "react";
import { theme } from "antd";

/**
 * Colours for charts and status marks, all taken from the host theme tokens so
 * light and dark both work. Following the A-share convention, "up" is red and
 * "down" is green.
 */
export function useVisual() {
  const { token } = theme.useToken();
  return useMemo(
    () => ({
      palette: [
        token.colorPrimary,
        token.purple,
        token.cyan,
        token.orange,
        token.geekblue,
        token.magenta,
        token.gold,
        token.lime,
        token.volcano,
        token.green,
        token.blue,
      ],
      primary: token.colorPrimary,
      up: token.colorError,
      down: token.colorSuccess,
      warning: token.colorWarning,
      danger: token.colorError,
      success: token.colorSuccess,
      info: token.colorInfo,
      purple: token.purple,
      cyan: token.cyan,
      orange: token.orange,
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
