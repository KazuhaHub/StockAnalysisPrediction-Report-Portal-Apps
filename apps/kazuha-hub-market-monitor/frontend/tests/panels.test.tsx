import { render } from "@testing-library/react";
import { expect, test } from "vitest";
import { Panel, Panels, layoutPanels } from "../src/components/Panels";

const kinds = (...k: ("pair" | "wide" | "detail")[]) =>
  k.map((kind, i) => ({ kind, key: String(i) }));
const keys = (rows: { kind: string; key: string }[][]) =>
  rows.map((row) => row.map((p) => p.key).join("+"));

test("short panels pair up two to a row", () => {
  expect(keys(layoutPanels(kinds("pair", "pair", "pair", "pair")))).toEqual([
    "0+1",
    "2+3",
  ]);
});

test("a short panel left alone takes the full width", () => {
  expect(keys(layoutPanels(kinds("pair", "pair", "pair")))).toEqual([
    "0+1",
    "2",
  ]);
  // A wide panel breaks a pair: the short one before it is alone.
  expect(keys(layoutPanels(kinds("pair", "wide", "pair", "pair")))).toEqual([
    "0",
    "1",
    "2+3",
  ]);
});

test("detail panels go to the bottom, full width, in their order", () => {
  expect(
    keys(layoutPanels(kinds("pair", "detail", "pair", "detail", "pair"))),
  ).toEqual(["0+2", "4", "1", "3"]);
});

test("cards of a pair stretch to the row's height", () => {
  const { container } = render(
    <Panels>
      <Panel title="A">short</Panel>
      <Panel title="B">
        <div style={{ height: 400 }}>tall</div>
      </Panel>
      {false}
      <Panel kind="detail" title="Detail">
        table
      </Panel>
    </Panels>,
  );
  const rows = container.querySelectorAll(".mm-panels > .ant-row");
  expect(rows).toHaveLength(2);
  const pair = rows[0].querySelectorAll(":scope > .ant-col");
  expect(pair).toHaveLength(2);
  pair.forEach((col) => {
    expect(col.className).toContain("ant-col-lg-12");
    expect(col.classList.contains("mm-panel-col")).toBe(true);
    expect(col.querySelector(".ant-card")?.classList.contains("mm-panel")).toBe(
      true,
    );
  });
  // The detail row holds one full-width column.
  const detail = rows[1].querySelectorAll(":scope > .ant-col");
  expect(detail).toHaveLength(1);
  expect(detail[0].className).toContain("ant-col-lg-24");
  expect(rows[1].textContent).toContain("Detail");
});

test("non-panel children render after the grid, outside any row", () => {
  const { container } = render(
    <Panels>
      <Panel title="A">a</Panel>
      <aside data-testid="drawer">drawer</aside>
    </Panels>,
  );
  const drawer = container.querySelector("[data-testid=drawer]")!;
  expect(drawer.closest(".ant-row")).toBeNull();
  expect(container.querySelectorAll(".mm-panels > .ant-row")).toHaveLength(1);
});

test("panels grouped in a fragment are laid out like the others", () => {
  const { container } = render(
    <Panels>
      <>
        <Panel title="A">a</Panel>
        <Panel title="B">b</Panel>
      </>
    </Panels>,
  );
  const rows = container.querySelectorAll(".mm-panels > .ant-row");
  expect(rows).toHaveLength(1);
  expect(rows[0].querySelectorAll(":scope > .ant-col")).toHaveLength(2);
});
