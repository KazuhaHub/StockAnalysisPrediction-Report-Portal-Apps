import { Fragment, type ReactNode } from "react";
import { Tag } from "antd";
import { useVisual } from "./useVisual";

const TOKEN =
  /(\*\*[\s\S]+?\*\*|`[^`]+`|~~[\s\S]+?~~|\[\[(?:ok|warn|no|up|down):[\s\S]+?\]\])/;
// Validation flags are statuses, never red or green (docs/charts.md).
const FLAG = { ok: "processing", warn: "warning", no: "orange" } as const;

/** A signed number inside rich text: red up, green down (docs/charts.md). */
function SignText({ dir, text }: { dir: "up" | "down"; text: string }) {
  const v = useVisual();
  return <span style={{ color: dir === "up" ? v.up : v.down }}>{text}</span>;
}

/**
 * Locale strings carry a little inline markup instead of HTML: **bold**,
 * `code`, ~~muted~~ (may nest the others), [[ok|warn|no:flag]], a signed
 * number [[up:+1.2]] / [[down:-1.2]] (see sx in lib/quant.ts) and "\n" for a
 * line break. Nothing here reaches innerHTML.
 */
export function rich(text: string): ReactNode {
  return text.split(TOKEN).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4)
      return <b key={i}>{rich(part.slice(2, -2))}</b>;
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2)
      return <code key={i}>{part.slice(1, -1)}</code>;
    if (part.startsWith("~~") && part.endsWith("~~") && part.length > 4)
      return (
        <span key={i} className="mm-why">
          {rich(part.slice(2, -2))}
        </span>
      );
    const sign = /^\[\[(up|down):([\s\S]+)\]\]$/.exec(part);
    if (sign)
      return <SignText key={i} dir={sign[1] as "up" | "down"} text={sign[2]} />;
    const flag = /^\[\[(ok|warn|no):([\s\S]+)\]\]$/.exec(part);
    if (flag)
      return (
        <Tag key={i} color={FLAG[flag[1] as keyof typeof FLAG]}>
          {flag[2]}
        </Tag>
      );
    return (
      <Fragment key={i}>
        {part.split("\n").map((line, j) => (
          <Fragment key={j}>
            {j > 0 && <br />}
            {line}
          </Fragment>
        ))}
      </Fragment>
    );
  });
}
