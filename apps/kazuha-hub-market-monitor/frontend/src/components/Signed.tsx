import { isNum, signed, DASH, type Num } from "../lib/format";
import { useVisual } from "./useVisual";

/**
 * A signed number the way A-share terminals show it (docs/charts.md): red
 * with "+" when positive, green with "-" when negative, the default text
 * colour at zero, a dash when missing.
 */
export function Signed({
  value,
  digits = 1,
  suffix = "",
  scale = 1,
}: {
  value: Num;
  digits?: number;
  suffix?: string;
  /** Multiplies the value first, e.g. 100 for a ratio shown in percent. */
  scale?: number;
}) {
  const v = useVisual();
  if (!isNum(value)) return <>{DASH}</>;
  const x = value * scale;
  return (
    <span style={{ color: v.sign(x) }}>{`${signed(x, digits)}${suffix}`}</span>
  );
}

/**
 * A copy template with one signed number in it, e.g. "距60日高 {v}%": the
 * placeholder and the unit right after it ("%", "pp") become a <Signed>, the
 * rest stays plain text.
 */
export function SignedIn({
  template,
  value,
  digits = 1,
  name = "v",
}: {
  template: string;
  value: Num;
  digits?: number;
  name?: string;
}) {
  const at = template.indexOf(`{${name}}`);
  if (at < 0) return <>{template}</>;
  const rest = template.slice(at + name.length + 2);
  const unit = /^(pp|%)/.exec(rest)?.[0] ?? "";
  return (
    <>
      {template.slice(0, at)}
      <Signed value={value} digits={digits} suffix={unit} />
      {rest.slice(unit.length)}
    </>
  );
}
