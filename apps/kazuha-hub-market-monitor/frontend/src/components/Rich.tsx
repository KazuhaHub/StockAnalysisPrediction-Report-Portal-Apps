import { Fragment, type ReactNode } from "react";
import { Tag } from "antd";

const TOKEN =
  /(\*\*[\s\S]+?\*\*|`[^`]+`|~~[\s\S]+?~~|\[\[(?:ok|warn|no):[\s\S]+?\]\])/;
const FLAG = { ok: "success", warn: "warning", no: "error" } as const;

/**
 * Locale strings carry a little inline markup instead of HTML: **bold**,
 * `code`, ~~muted~~ (may nest the others), [[ok|warn|no:flag]] and "\n" for a
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
