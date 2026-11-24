import { render } from "@testing-library/react";
import { theme } from "antd";
import { expect, test } from "vitest";
import { Signed } from "../src/components/Signed";

const token = theme.getDesignToken();
const colorOf = (el: Element | null) =>
  (el as HTMLElement | null)?.style.color ?? "";
const rgb = (hex: string) => {
  const n = parseInt(hex.slice(1), 16);
  return `rgb(${n >> 16}, ${(n >> 8) & 255}, ${n & 255})`;
};

test("a signed number is red with + above zero, green below, plain at zero", () => {
  const { container } = render(
    <>
      <Signed value={1.234} digits={1} suffix="%" />
      <Signed value={-0.5} digits={2} />
      <Signed value={0} />
      <Signed value={null} />
      <Signed value={0.123} scale={100} suffix="%" />
    </>,
  );
  const spans = container.querySelectorAll("span");
  expect(spans[0].textContent).toBe("+1.2%");
  expect(colorOf(spans[0])).toBe(rgb(token.colorError));
  expect(spans[1].textContent).toBe("-0.50");
  expect(colorOf(spans[1])).toBe(rgb(token.colorSuccess));
  expect(spans[2].textContent).toBe("0.0");
  expect(colorOf(spans[2])).toBe("");
  expect(container.textContent).toContain("—");
  expect(spans[3].textContent).toBe("+12.3%");
});
