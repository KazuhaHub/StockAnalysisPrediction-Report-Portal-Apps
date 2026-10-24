import {
  createContext,
  useContext,
  useEffect,
  useId,
  useState,
  type ReactNode,
} from "react";
import { Checkbox, Form, Input, InputNumber, Select } from "antd";
import type { Client, Locale } from "./client";
import enUS from "../locales/en-US.json";
import zhCN from "../locales/zh-CN.json";
import zhTW from "../locales/zh-TW.json";

export const locales = { "en-US": enUS, "zh-CN": zhCN, "zh-TW": zhTW };
export interface UI {
  client: Client;
  t(key: string): string;
  locale: Locale;
  busy: boolean;
  admin: boolean;
  error: string;
  revision: number;
  run(action: () => Promise<unknown>, notice?: string): Promise<boolean>;
}
export const UIContext = createContext<UI>(null!);
export const useUI = () => useContext(UIContext);
export function Field({
  label,
  value,
  onChange,
  secret = false,
  multiline = false,
  help,
}: {
  label: string;
  value?: string;
  onChange(value: string): void;
  secret?: boolean;
  multiline?: boolean;
  help?: ReactNode;
}) {
  const id = useId(),
    props = {
      id,
      value: value ?? "",
      onChange: (
        e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
      ) => onChange(e.target.value),
      autoComplete: secret ? "new-password" : "off",
    };
  return (
    <Form.Item label={label} htmlFor={id} extra={help}>
      {secret ? (
        <Input.Password {...props} visibilityToggle={false} />
      ) : multiline ? (
        <Input.TextArea {...props} autoSize={{ minRows: 2, maxRows: 6 }} />
      ) : (
        <Input {...props} />
      )}
    </Form.Item>
  );
}
export function NumberField({
  label,
  value,
  onChange,
  min,
  max,
}: {
  label: string;
  value: number;
  onChange(value: number): void;
  min: number;
  max: number;
}) {
  const id = useId();
  return (
    <Form.Item label={label} htmlFor={id}>
      <InputNumber
        id={id}
        value={value}
        min={min}
        max={max}
        precision={0}
        onChange={(v) => onChange(v ?? min)}
        style={{ width: "100%" }}
      />
    </Form.Item>
  );
}
export function Choice({
  label,
  value,
  options,
  onChange,
  multiple = false,
  disabled = false,
  help,
}: {
  label: string;
  value: string | string[];
  options: { value: string; label: string }[];
  onChange(value: string | string[]): void;
  multiple?: boolean;
  disabled?: boolean;
  help?: ReactNode;
}) {
  const id = useId();
  return (
    <Form.Item label={label} htmlFor={id} extra={help}>
      <Select
        virtual={false}
        id={id}
        aria-label={label}
        value={value}
        options={options}
        onChange={onChange}
        mode={multiple ? "multiple" : undefined}
        showSearch={{ optionFilterProp: "label" }}
        disabled={disabled}
        style={{ width: "100%" }}
      />
    </Form.Item>
  );
}
export function Check({
  children,
  checked,
  onChange,
}: {
  children: ReactNode;
  checked: boolean;
  onChange(value: boolean): void;
}) {
  return (
    <Form.Item>
      <Checkbox checked={checked} onChange={(e) => onChange(e.target.checked)}>
        {children}
      </Checkbox>
    </Form.Item>
  );
}
export function useResource<T>(load: () => Promise<T>, initial: T) {
  const [data, setData] = useState(initial),
    [loading, setLoading] = useState(true),
    [error, setError] = useState("");
  const { t } = useUI();
  useEffect(() => {
    let live = true;
    setLoading(true);
    setError("");
    load()
      .then((value) => {
        if (live) setData(value);
      })
      .catch((e) => {
        if (live) {
          setData(initial);
          setError(t(e.key ?? "unavailable"));
        }
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [load]);
  return { data, loading, error };
}
export const date = (value: string | undefined, locale: string) =>
  value ? new Date(value).toLocaleString(locale) : "—";
