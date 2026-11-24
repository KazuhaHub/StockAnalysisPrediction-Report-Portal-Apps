import { Segmented, Select } from "antd";
import { useNarrow } from "../lib/useNarrow";

/** Options of a choice that fold to a Select on a phone. */
export const FOLD_AT = 3;

type Props<V extends string | number> = {
  /** Names the control for assistive technology; it has no visible label. */
  label: string;
  value: V;
  onChange: (value: V) => void;
  options: { label: string; value: V }[];
};

/**
 * A small segmented choice for a card header. Below 768px a choice of three or
 * more options becomes a small Select, so the header stays on one line; two
 * options always fit and stay segmented.
 */
export function FoldSegmented<V extends string | number>({
  label,
  value,
  onChange,
  options,
}: Props<V>) {
  const narrow = useNarrow();
  if (narrow && options.length >= FOLD_AT)
    return (
      <Select<V>
        size="small"
        aria-label={label}
        className="mm-fold-select"
        value={value}
        onChange={(next) => onChange(next)}
        options={options}
      />
    );
  return (
    <Segmented<V>
      size="small"
      aria-label={label}
      value={value}
      onChange={onChange}
      options={options}
    />
  );
}
