import { isValidElement, useState, type Key, type ReactNode } from "react";
import { Button, Select, Table } from "antd";
import type { TableColumnType, TableProps } from "antd";
import { useCopy } from "../lib/copy";
import { usePhone } from "../lib/useNarrow";

/** A column may name itself for the phone card when its title is not plain text. */
export type CardColumn<T> = TableColumnType<T> & { phoneLabel?: string };

type Order = "ascend" | "descend";
type Sort = { key: string; order: Order };

const columnKey = <T,>(column: TableColumnType<T>): string | undefined => {
  if (column.key !== undefined && column.key !== null)
    return String(column.key);
  if ("dataIndex" in column && column.dataIndex !== undefined)
    return Array.isArray(column.dataIndex)
      ? column.dataIndex.join(".")
      : String(column.dataIndex);
  return undefined;
};

// The visible text of a title written as markup (a tooltip span around the name).
const textOf = (node: ReactNode): string => {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (isValidElement<{ children?: ReactNode }>(node))
    return textOf(node.props.children);
  return "";
};

const columnLabel = <T,>(column: CardColumn<T>): string =>
  column.phoneLabel ??
  (textOf(column.title as ReactNode).trim() || (columnKey(column) ?? ""));

/**
 * antd's Table, which on a phone lays each row out as a card of label and
 * value instead of a row of columns: a phone cannot show six columns, and a
 * sideways scroll hides most of them. Everything else is antd's own (sorting,
 * pagination, expansion, row events); this labels the cells, drops the
 * horizontal scroll where the cards make it unnecessary (`.mm-card-table--cards`
 * in style.css) and, because a card has no header to click, offers the sort
 * as a small control above the cards.
 *
 * A table that owns its order (a column with `sortOrder`, as RowTable) is told
 * about a sort through `onChange` exactly as a header click would tell it; any
 * other table is sorted here, by the column's own `sorter`.
 */
export function CardTable<T>(props: TableProps<T>) {
  const { copy } = useCopy();
  const phone = usePhone();
  const source = (props.columns ?? []) as CardColumn<T>[];
  const [own, setOwn] = useState<Sort | null>(() => {
    const first = source.find((c) => c.sorter && c.defaultSortOrder);
    const key = first ? columnKey(first) : undefined;
    return first && key
      ? { key, order: first.defaultSortOrder as Order }
      : null;
  });

  const sortables = phone ? source.filter((c) => c.sorter && columnKey(c)) : [];
  const controlled = sortables.some((c) => c.sortOrder !== undefined);
  const owned = controlled ? sortables.find((c) => c.sortOrder) : undefined;
  const current: Sort | null = controlled
    ? owned
      ? { key: columnKey(owned)!, order: owned.sortOrder as Order }
      : null
    : own;

  const apply = (next: Sort | null) => {
    if (!controlled) {
      setOwn(next);
      return;
    }
    const column = next
      ? sortables.find((c) => columnKey(c) === next.key)
      : owned;
    props.onChange?.(
      {},
      {},
      {
        column,
        columnKey: next?.key,
        field:
          column && "dataIndex" in column
            ? (column.dataIndex as Key | readonly Key[] | undefined)
            : undefined,
        order: next?.order,
      },
      { action: "sort", currentDataSource: [...(props.dataSource ?? [])] },
    );
  };

  // The first column names the row; on a card it is the title, not a labelled field.
  const columns = source.map((c, i) => {
    const label = columnLabel(c);
    const card =
      i === 0
        ? { "data-label": label, "data-primary": "" }
        : { "data-label": label };
    const key = columnKey(c);
    return {
      ...c,
      // Cards do not scroll sideways, so nothing needs pinning; antd's pin shadow would overhang the card.
      fixed: phone ? undefined : c.fixed,
      ...(!controlled && sortables.includes(c)
        ? { sortOrder: current && current.key === key ? current.order : null }
        : {}),
      onCell: (record: T, index?: number) =>
        ({
          ...(c.onCell?.(record, index) ?? {}),
          ...card,
        }) as ReturnType<NonNullable<TableColumnType<T>["onCell"]>>,
    };
  });
  const className = [
    props.className,
    "mm-card-table",
    phone && "mm-card-table--cards",
  ]
    .filter(Boolean)
    .join(" ");
  // A vertical scroll still bounds a long list; only the sideways one goes.
  const scroll = phone
    ? props.scroll?.y
      ? { y: props.scroll.y }
      : undefined
    : props.scroll;

  return (
    <>
      {sortables.length > 0 && (
        <div className="mm-card-sort">
          <Select
            size="small"
            aria-label={copy.table_sortBy}
            value={current?.key ?? ""}
            onChange={(key: string) =>
              apply(key === "" ? null : { key, order: "descend" })
            }
            options={[
              { value: "", label: copy.table_sortDefault },
              ...sortables.map((c) => ({
                value: columnKey(c)!,
                label: columnLabel(c),
              })),
            ]}
          />
          {current && (
            <Button
              size="small"
              aria-label={
                current.order === "descend"
                  ? copy.table_sortDesc
                  : copy.table_sortAsc
              }
              title={
                current.order === "descend"
                  ? copy.table_sortDesc
                  : copy.table_sortAsc
              }
              onClick={() =>
                apply({
                  key: current.key,
                  order: current.order === "descend" ? "ascend" : "descend",
                })
              }
            >
              {current.order === "descend" ? "↓" : "↑"}
            </Button>
          )}
        </div>
      )}
      <Table<T>
        {...props}
        columns={columns}
        className={className}
        scroll={scroll}
      />
    </>
  );
}
