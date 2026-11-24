import { render } from "@testing-library/react";
import { theme } from "antd";
import { expect, test } from "vitest";
import { Signed, SignedIn } from "../src/components/Signed";

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

test("SignedIn signs the number in a caption and keeps its unit with it", () => {
  const { container } = render(
    <>
      <SignedIn template="距60日高 {v}%" value={-43.8} />
      <SignedIn template="{v}pp 修复" value={1.9} />
      <SignedIn template="无占位符" value={1} />
    </>,
  );
  const spans = container.querySelectorAll("span");
  expect(spans[0].textContent).toBe("-43.8%");
  expect(colorOf(spans[0])).toBe(rgb(token.colorSuccess));
  expect(spans[1].textContent).toBe("+1.9pp");
  expect(container.textContent).toContain("距60日高 -43.8%");
  expect(container.textContent).toContain("无占位符");
});

test("the shown value decides sign and colour: 0.04 at one digit is a plain 0.0", () => {
  const { container } = render(<Signed value={0.04} digits={1} />);
  const span = container.querySelector("span")!;
  expect(span.textContent).toBe("0.0");
  expect(colorOf(span)).toBe("");
});
