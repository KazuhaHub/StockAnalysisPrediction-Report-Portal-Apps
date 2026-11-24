import { rich } from "../components/Rich";
import { useCopy } from "../lib/copy";
import { fill } from "../lib/format";

type Block =
  | { kind: "h"; key: string }
  | { kind: "note"; key: string }
  | {
      kind: "table";
      id: string;
      cols: number;
      head: boolean;
      /** Column widths in px; undefined is flexible. */
      widths?: (number | undefined)[];
      /** Columns drawn muted and small. */
      muted?: number[];
    };

const h = (key: string): Block => ({ kind: "h", key });
const note = (key: string): Block => ({ kind: "note", key });
const table = (
  id: string,
  cols: number,
  head: boolean,
  widths?: (number | undefined)[],
  muted?: number[],
): Block => ({ kind: "table", id, cols, head, widths, muted });

/** The order of the methodology; text is in the locales as qm_* keys. */
const BLOCKS: Block[] = [
  note("qm_lead"),
  h("qm_h1"),
  table("t1", 3, true, [132, undefined, 376], [2]),
  h("qm_h2"),
  table("t2", 3, true, [104, undefined, 196]),
  note("qm_n2"),
  h("qm_h3"),
  table("t3", 2, true, [120]),
  h("qm_h4"),
  table("t4", 2, false, [120]),
  h("qm_h5"),
  table("t5", 3, true, [150, undefined, 270], [2]),
  note("qm_n5"),
  h("qm_h6"),
  note("qm_n6a"),
  table("t6a", 3, true, [112, undefined, 280], [2]),
  table("t6b", 4, true, [112, 130, undefined, 210], [3]),
  note("qm_n6b"),
  table("t6c", 5, true, [170]),
  note("qm_n6c"),
  h("qm_h7"),
  note("qm_n7a"),
  table("t7a", 3, true, [112, undefined, 300], [2]),
  table("t7b", 6, true, [196]),
  note("qm_n7b"),
  h("qm_h8"),
  table("t8", 3, true, [118, undefined, 210], [2]),
  note("qm_n8"),
];

/** The 口径说明 body. `vars` fills the live numbers (`{hold1}`, `{delisted}`, ...) the cells name. */
export function QuantMethod({ vars }: { vars: Record<string, string> }) {
  const { copy } = useCopy();
  const text = (key: string) => (copy as Record<string, string>)[key];
  const has = (key: string) => Object.hasOwn(copy, key);
  const cell = (key: string) => rich(fill(text(key), vars));
  return (
    <div className="mm-spec">
      {BLOCKS.map((block, bi) => {
        if (block.kind === "h") return <h4 key={bi}>{text(block.key)}</h4>;
        if (block.kind === "note")
          return (
            <div key={bi} className="mm-spec-note">
              {cell(block.key)}
            </div>
          );
        const { id, cols, widths = [], muted = [] } = block;
        const rows: number[] = [];
        while (has(`qm_${id}_${rows.length}_0`)) rows.push(rows.length);
        return (
          <div key={bi} className="mm-spec-scroll">
            <table data-table={id}>
              {block.head && (
                <thead>
                  <tr>
                    {Array.from({ length: cols }, (_, c) => (
                      <th
                        key={c}
                        style={widths[c] ? { width: widths[c] } : undefined}
                      >
                        {text(`qm_${id}_h${c}`)}
                      </th>
                    ))}
                  </tr>
                </thead>
              )}
              <tbody>
                {rows.map((r) => {
                  const present = Array.from(
                    { length: cols },
                    (_, c) => c,
                  ).filter((c) => has(`qm_${id}_${r}_${c}`));
                  return (
                    <tr key={r}>
                      {present.map((c, i) => (
                        <td
                          key={c}
                          colSpan={
                            i === present.length - 1
                              ? cols - present.length + 1
                              : undefined
                          }
                          className={
                            c === 0
                              ? "mm-spec-k"
                              : muted.includes(c)
                                ? "mm-why"
                                : undefined
                          }
                        >
                          {cell(`qm_${id}_${r}_${c}`)}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        );
      })}
    </div>
  );
}
