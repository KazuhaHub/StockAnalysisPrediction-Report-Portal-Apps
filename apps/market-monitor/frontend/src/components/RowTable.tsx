import { useEffect, useMemo, useState } from "react";
import { Alert, Table } from "antd";
import type { TableColumnsType, TableProps } from "antd";
import { useCopy } from "../lib/copy";
import { fill } from "../lib/format";
import { usePagedRows, type RowQuery } from "../lib/hooks";
import type { ModuleId } from "../lib/api";

export const PAGE_SIZE = 20;

type Props<R> = {
  module: ModuleId;
  date: string;
  revision: number;
  columns: TableColumnsType<R>;
  /** Field the table is sorted by, descending, until a column is clicked. */
  defaultSort: string;
  q: string;
  filters: Record<string, string | undefined>;
  scrollX: number;
  /** When set, rows are interactive: click, Enter and Space select them. */
  onSelect?(row: R): void;
};

type View = {
  /** Resets `page` when it changes (search, filters, date, default sort). */
  key: string;
  page: number;
  /** The user's sort; `null` follows `defaultSort`. */
  sort: { field: string; order: "asc" | "desc" } | null;
};

/**
 * A server-paged, server-sorted and server-filtered table: every interaction
 * becomes `/rows` query parameters, and only one page is ever held.
 * Columns marked `sorter: true` sort on their `dataIndex`. The sort cycle of a
 * column is descending, ascending, then back to the default sort (never to
 * unsorted file order). A sort on a column that is no longer shown is dropped.
 */
export function RowTable<R extends { code: string }>({
  module,
  date,
  revision,
  columns,
  defaultSort,
  q,
  filters,
  scrollX,
  onSelect,
}: Props<R>) {
  const { copy } = useCopy();
  const resetKey = JSON.stringify([date, q, filters, defaultSort]);
  const [view, setView] = useState<View>({
    key: resetKey,
    page: 1,
    sort: null,
  });
  const sortable = new Set(
    columns.flatMap((column) =>
      column.sorter && "dataIndex" in column ? [String(column.dataIndex)] : [],
    ),
  );
  const sortKey = [...sortable].join("|");
  // A sort on a column the current view does not show goes back to default.
  useEffect(() => {
    setView((prev) =>
      prev.sort && !sortKey.split("|").includes(prev.sort.field)
        ? { ...prev, sort: null, page: 1 }
        : prev,
    );
  }, [sortKey]);
  // Searching, filtering, switching date or default sort starts at page 1.
  const page = view.key === resetKey ? view.page : 1;
  const userSort =
    view.sort && sortable.has(view.sort.field) ? view.sort : null;
  const sort = userSort ?? { field: defaultSort, order: "desc" as const };
  const query = useMemo<RowQuery>(
    () => ({
      page,
      size: PAGE_SIZE,
      sort: sort.field,
      order: sort.order,
      q: q || undefined,
      filters,
    }),
    [page, sort.field, sort.order, q, filters],
  );
  const { items, total, loading, error } = usePagedRows<R>(
    module,
    date,
    query,
    revision,
  );

  const cols = columns.map((column) => {
    if (!column.sorter || !("dataIndex" in column)) return column;
    return {
      ...column,
      sortDirections: ["descend", "ascend"] as ("descend" | "ascend")[],
      sortOrder:
        sort.field === String(column.dataIndex)
          ? sort.order === "asc"
            ? ("ascend" as const)
            : ("descend" as const)
          : null,
    };
  });

  const onChange: TableProps<R>["onChange"] = (
    pagination,
    _filters,
    sorter,
    extra,
  ) => {
    if (extra.action === "sort") {
      const one = Array.isArray(sorter) ? sorter[0] : sorter;
      const field = one?.field ? String(one.field) : "";
      setView({
        key: resetKey,
        page: 1,
        sort:
          one?.order && field
            ? { field, order: one.order === "ascend" ? "asc" : "desc" }
            : null,
      });
    } else {
      setView({
        key: resetKey,
        page: pagination.current ?? 1,
        sort: view.sort,
      });
    }
  };

  const select = (row: R) => onSelect?.(row);
  return (
    <>
      {error && error !== "no_data" && (
        <Alert
          type="error"
          showIcon
          title={copy.unavailable}
          style={{ marginBottom: 8 }}
        />
      )}
      <Table<R>
        size="small"
        rowKey="code"
        loading={loading}
        columns={cols}
        dataSource={items}
        scroll={{ x: scrollX }}
        onChange={onChange}
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total,
          showSizeChanger: false,
          showTotal: (count) => fill(copy.totalRows, { n: count }),
        }}
        onRow={
          onSelect
            ? (row) => ({
                onClick: () => select(row),
                onKeyDown: (event) => {
                  // Keys pressed inside a nested control are not the row's.
                  if (event.target !== event.currentTarget) return;
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    select(row);
                  }
                },
                tabIndex: 0,
                className: "mm-row-select",
              })
            : undefined
        }
      />
    </>
  );
}
