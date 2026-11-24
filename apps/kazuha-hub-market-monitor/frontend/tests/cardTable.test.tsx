import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { TableColumnsType } from "antd";
import enUS from "../locales/en-US.json";
import { CardTable } from "../src/components/CardTable";
import { setViewport } from "./viewport";

vi.mock("../src/lib/copy", () => ({
  useCopy: () => ({ copy: enUS, locale: "en-US", timeZone: "UTC" }),
}));

type Row = { id: number; name: string; size: number };
const rows: Row[] = [
  { id: 1, name: "alpha", size: 3 },
  { id: 2, name: "beta", size: 9 },
  { id: 3, name: "gamma", size: 5 },
];
const columns: TableColumnsType<Row> = [
  { title: "Name", dataIndex: "name", key: "name" },
  { title: () => "Size", dataIndex: "size", key: "size" },
];
const sortable: TableColumnsType<Row> = [
  { title: "Name", dataIndex: "name", key: "name" },
  {
    title: "Size",
    dataIndex: "size",
    key: "size",
    sorter: (a, b) => a.size - b.size,
  },
];
const names = (container: HTMLElement) =>
  [
    ...container.querySelectorAll(
      ".ant-table-tbody tr.ant-table-row td:first-child",
    ),
  ].map((td) => td.textContent);

describe("CardTable", () => {
  it("is an ordinary table on a wide screen", () => {
    const { container } = render(
      <CardTable<Row>
        rowKey="id"
        columns={columns}
        dataSource={rows}
        scroll={{ x: 900 }}
      />,
    );
    expect(container.querySelector(".ant-table-thead")).not.toBeNull();
    expect(container.querySelector(".mm-card-table--cards")).toBeNull();
    expect(container.querySelector(".mm-card-sort")).toBeNull();
  });

  // A title written as markup (a tooltip span) still labels its cards with its text, never with
  // the column's identifier.
  it("labels a card with the text of a title written as markup", () => {
    setViewport(390);
    const { container } = render(
      <CardTable<Row>
        rowKey="id"
        columns={[
          columns[0],
          {
            ...columns[1],
            title: (
              <span title="tip">
                <b>Breadth</b> %
              </span>
            ),
          } as never,
        ]}
        dataSource={rows}
      />,
    );
    const cells = [
      ...container.querySelectorAll(
        ".ant-table-tbody tr.ant-table-row:first-child td",
      ),
    ];
    expect(cells.map((c) => c.getAttribute("data-label"))).toEqual([
      "Name",
      "Breadth %",
    ]);
  });

  // On a phone each row is a card of label and value, so nothing needs a sideways scroll.
  it("turns rows into labelled cards on a phone, without a horizontal scroll", () => {
    setViewport(390);
    const { container } = render(
      <CardTable<Row>
        rowKey="id"
        className="mine"
        columns={[columns[0], { ...columns[1], phoneLabel: "Size" } as never]}
        dataSource={rows}
        scroll={{ x: 900 }}
      />,
    );
    const wrapper = container.querySelector(".ant-table-wrapper")!;
    expect(wrapper.classList.contains("mm-card-table--cards")).toBe(true);
    expect(wrapper.classList.contains("mine")).toBe(true);
    const cells = [
      ...container.querySelectorAll(
        ".ant-table-tbody tr.ant-table-row:first-child td",
      ),
    ];
    expect(cells.map((c) => c.getAttribute("data-label"))).toEqual([
      "Name",
      "Size",
    ]);
    expect(
      container.querySelector(".ant-table-content")?.getAttribute("style") ??
        "",
    ).not.toContain("overflow-x: auto");
  });

  // A pinned column has nothing to stay put against in a card, and antd's pin
  // shadow would reach past the card's edge and push the page sideways.
  it("unpins columns on a phone and keeps them pinned on a wide screen", () => {
    const pinned: TableColumnsType<Row> = [
      { ...columns[0], fixed: "left" },
      { ...columns[1], fixed: "right" },
    ];
    const pinnedSelector =
      ".ant-table-cell-fix-start, .ant-table-cell-fix-end, .ant-table-cell-fix-left, .ant-table-cell-fix-right";
    setViewport(390);
    const phone = render(
      <CardTable<Row>
        rowKey="id"
        columns={pinned}
        dataSource={rows}
        scroll={{ x: 900 }}
      />,
    );
    expect(phone.container.querySelector(pinnedSelector)).toBeNull();
    phone.unmount();
    setViewport(1280);
    const wide = render(
      <CardTable<Row>
        rowKey="id"
        columns={pinned}
        dataSource={rows}
        scroll={{ x: 900 }}
      />,
    );
    expect(
      wide.container.querySelector(`.ant-table-tbody ${pinnedSelector}`),
    ).not.toBeNull();
  });

  it("keeps a column's own cell props, and the first column is the card title", () => {
    setViewport(390);
    const own: TableColumnsType<Row> = [
      { ...columns[0], onCell: () => ({ title: "own" }) },
      columns[1],
    ];
    const { container } = render(
      <CardTable<Row> rowKey="id" columns={own} dataSource={rows} />,
    );
    const cells = [
      ...container.querySelectorAll(
        ".ant-table-tbody tr.ant-table-row:first-child td",
      ),
    ];
    expect(cells[0].getAttribute("title")).toBe("own");
    expect(cells[0].hasAttribute("data-primary")).toBe(true);
    expect(cells[1].hasAttribute("data-primary")).toBe(false);
  });

  it("keeps rows clickable", async () => {
    setViewport(390);
    const onClick = vi.fn();
    const { container } = render(
      <CardTable<Row>
        rowKey="id"
        columns={columns}
        dataSource={rows}
        onRow={(row) => ({ onClick: () => onClick(row.id) })}
      />,
    );
    await userEvent.click(container.querySelector("tr.ant-table-row")!);
    expect(onClick).toHaveBeenCalledWith(1);
  });
});

// The header is hidden in cards, so a phone sorts from a control above them.
describe("CardTable sorting on a phone", () => {
  const pick = async (label: string) => {
    await userEvent.click(
      screen.getByRole("combobox", { name: enUS.table_sortBy }),
    );
    await userEvent.click(screen.getByTitle(label));
  };

  it("offers no control when no column sorts", () => {
    setViewport(390);
    const { container } = render(
      <CardTable<Row> rowKey="id" columns={columns} dataSource={rows} />,
    );
    expect(container.querySelector(".mm-card-sort")).toBeNull();
  });

  it("sorts rows the table holds, descending first, and flips and clears", async () => {
    setViewport(390);
    const { container } = render(
      <CardTable<Row> rowKey="id" columns={sortable} dataSource={rows} />,
    );
    expect(names(container)).toEqual(["alpha", "beta", "gamma"]);
    await pick("Size");
    expect(names(container)).toEqual(["beta", "gamma", "alpha"]);
    await userEvent.click(
      screen.getByRole("button", { name: enUS.table_sortDesc }),
    );
    expect(names(container)).toEqual(["alpha", "gamma", "beta"]);
    expect(
      screen.getByRole("button", { name: enUS.table_sortAsc }),
    ).toBeTruthy();
    await pick(enUS.table_sortDefault);
    expect(names(container)).toEqual(["alpha", "beta", "gamma"]);
    expect(
      screen.queryByRole("button", { name: enUS.table_sortAsc }),
    ).toBeNull();
  });

  it("starts from a column's default sort order", () => {
    setViewport(390);
    const { container } = render(
      <CardTable<Row>
        rowKey="id"
        columns={[sortable[0], { ...sortable[1], defaultSortOrder: "ascend" }]}
        dataSource={rows}
      />,
    );
    expect(names(container)).toEqual(["alpha", "gamma", "beta"]);
  });

  // A server-sorted table (RowTable) owns the order: the control reports a
  // sort change the way a header click does and shows what the table says.
  it("reports a sort to a table that owns its order", async () => {
    setViewport(390);
    const onChange = vi.fn();
    const { rerender } = render(
      <CardTable<Row>
        rowKey="id"
        columns={[sortable[0], { ...sortable[1], sortOrder: null }]}
        dataSource={rows}
        onChange={onChange}
      />,
    );
    await pick("Size");
    expect(onChange).toHaveBeenCalledTimes(1);
    const [, , sorter, extra] = onChange.mock.calls[0];
    expect(sorter).toMatchObject({ field: "size", order: "descend" });
    expect(extra.action).toBe("sort");
    rerender(
      <CardTable<Row>
        rowKey="id"
        columns={[sortable[0], { ...sortable[1], sortOrder: "descend" }]}
        dataSource={rows}
        onChange={onChange}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: enUS.table_sortDesc }),
    );
    expect(onChange.mock.calls[1][2]).toMatchObject({
      field: "size",
      order: "ascend",
    });
    await pick(enUS.table_sortDefault);
    expect(onChange.mock.calls[2][2]).toMatchObject({ order: undefined });
    expect(within(document.body).getByRole("combobox")).toBeTruthy();
  });
});
