import {
  Children,
  isValidElement,
  type ReactElement,
  type ReactNode,
} from "react";
import { Card, Col, Row } from "antd";
import type { CardProps } from "antd";

/**
 * The page layout every module page uses below its KPI row and main chart
 * (docs/frontend-layout.md):
 *
 * - "pair": a short panel of bounded height. Two share a row on desktop and
 *   stretch to the same height; one left alone takes the full width.
 * - "wide": a bounded panel that needs the full width (a long time series).
 * - "detail": an open-ended panel that grows with the data (a per-item
 *   table). Always full width, and always after every other panel.
 */
export type PanelKind = "pair" | "wide" | "detail";

type PanelProps = Omit<CardProps, "size"> & {
  kind?: PanelKind;
  children?: ReactNode;
};

/** A card inside <Panels>. Rendered by Panels, which reads its kind. */
export function Panel({
  kind: _kind,
  children,
  className,
  ...card
}: PanelProps) {
  return (
    <Card
      size="small"
      className={["mm-panel", className].filter(Boolean).join(" ")}
      {...card}
    >
      {children}
    </Card>
  );
}

/** Groups panels into rows by the layout rule above. Exported for tests. */
export function layoutPanels<T extends { kind: PanelKind }>(
  panels: T[],
): T[][] {
  const rows: T[][] = [];
  let open: T | null = null;
  const flush = () => {
    if (open) rows.push([open]);
    open = null;
  };
  for (const p of panels.filter((p) => p.kind !== "detail")) {
    if (p.kind === "wide") {
      flush();
      rows.push([p]);
    } else if (open) {
      rows.push([open, p]);
      open = null;
    } else {
      open = p;
    }
  }
  flush();
  for (const p of panels.filter((p) => p.kind === "detail")) rows.push([p]);
  return rows;
}

/** Lays out its <Panel> children. Anything else (a drawer, a modal) is
 * rendered after the grid as it is. */
export function Panels({ children }: { children: ReactNode }) {
  const all = Children.toArray(children);
  const others = all.filter((c) => !(isValidElement(c) && c.type === Panel));
  const panels = all
    .filter(
      (c): c is ReactElement<PanelProps> =>
        isValidElement(c) && c.type === Panel,
    )
    .map((element, i) => ({
      element,
      kind: (element.props.kind ?? "pair") as PanelKind,
      key: String(element.key ?? i),
    }));
  return (
    <div className="mm-panels">
      {layoutPanels(panels).map((row) => (
        <Row gutter={[16, 16]} key={row.map((p) => p.key).join("+")}>
          {row.map((p) => (
            <Col
              key={p.key}
              xs={24}
              lg={row.length === 2 ? 12 : 24}
              className="mm-panel-col"
            >
              {p.element}
            </Col>
          ))}
        </Row>
      ))}
      {others}
    </div>
  );
}
