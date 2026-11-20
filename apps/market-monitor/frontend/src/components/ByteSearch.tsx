import { useId, useState } from "react";
import { Input } from "antd";
import { useCopy } from "../lib/copy";
import { MAX_QUERY_BYTES, utf8Length } from "../lib/format";

type Props = {
  placeholder: string;
  width: number;
  onSearch(value: string): void;
};

/**
 * A search box for a backend query value. The backend rejects values longer
 * than 64 bytes of UTF-8 (not characters), so an over-long value is flagged
 * inline and never submitted.
 */
export function ByteSearch({ placeholder, width, onSearch }: Props) {
  const { copy } = useCopy();
  const [value, setValue] = useState("");
  const tooLong = utf8Length(value.trim()) > MAX_QUERY_BYTES;
  const hintId = useId();
  return (
    <span style={{ display: "inline-flex", flexDirection: "column" }}>
      <Input.Search
        allowClear
        placeholder={placeholder}
        aria-label={placeholder}
        aria-invalid={tooLong}
        aria-describedby={tooLong ? hintId : undefined}
        status={tooLong ? "error" : undefined}
        value={value}
        onChange={(event) => {
          setValue(event.target.value);
        }}
        onSearch={(text) => {
          const trimmed = text.trim();
          if (utf8Length(trimmed) <= MAX_QUERY_BYTES) onSearch(trimmed);
        }}
        style={{ width }}
      />
      {tooLong && (
        <span id={hintId} role="alert" className="mm-hint">
          {copy.inputTooLong}
        </span>
      )}
    </span>
  );
}
