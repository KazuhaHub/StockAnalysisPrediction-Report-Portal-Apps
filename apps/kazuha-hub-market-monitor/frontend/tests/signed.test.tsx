import { render } from "@testing-library/react";
import { theme } from "antd";
import { expect, test } from "vitest";
import { Signed, SignedIn } from "../src/components/Signed";
import { rich } from "../src/components/Rich";
import { stateTone, sx } from "../src/lib/quant";
import { shown, tagProps } from "../src/lib/status";

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

test("sx marks a signed number for rich text, and rich colours it", () => {
  expect(sx(1.2)).toBe("[[up:+1.2]]");
  expect(sx(-0.5)).toBe("[[down:-0.5]]");
  expect(sx(0)).toBe("0");
  expect(sx(null)).toBe("—");
  const { container } = render(
    <p>{rich(`回撤 ${sx(-20)}% · **年化 ${sx(12.3)}%**`)}</p>,
  );
  const spans = container.querySelectorAll("span");
  expect(container.textContent).toBe("回撤 -20% · 年化 +12.3%");
  expect(colorOf(spans[0])).toBe(rgb(token.colorSuccess));
  expect(colorOf(spans[1])).toBe(rgb(token.colorError));
  expect(container.querySelector("b")?.textContent).toBe("年化 +12.3%");
});

test("each quant state has one tone for band, table and tag", () => {
  expect(stateTone("熊市确认")).toBe("danger");
  expect(stateTone("熊市确认（主跌延续）")).toBe("danger");
  expect(stateTone("下跌中")).toBe("danger");
  expect(stateTone("顶部警戒")).toBe("warning");
  expect(stateTone("过热")).toBe("warning");
  expect(stateTone("出清区")).toBe("info");
  expect(stateTone("确认区")).toBe("success");
  expect(stateTone("修复中")).toBe("success");
  expect(stateTone("常规")).toBe("neutral");
});

test("the most severe status tag is solid; shown() rounds before the sign", () => {
  expect(tagProps("orange-inverse")).toEqual({
    color: "orange",
    variant: "solid",
  });
  expect(tagProps("gold")).toEqual({ color: "gold" });
  expect(shown(0.03, 1)).toBe(0);
  expect(shown(-0.06, 1)).toBe(-0.1);
  expect(shown(undefined, 1)).toBeNull();
});
