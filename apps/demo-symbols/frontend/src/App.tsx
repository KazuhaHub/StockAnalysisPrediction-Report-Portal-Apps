import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Flex,
  Input,
  Table,
} from "antd";
import {
  PortalAppProvider,
  PortalClient,
  PortalPage,
  PortalLocaleSelect,
  usePortalLocale,
  type LocaleSelection,
  type Locale,
} from "@portal-app/sdk";
import enUS from "../locales/en-US.json";
import zhCN from "../locales/zh-CN.json";
import zhTW from "../locales/zh-TW.json";
import "./style.css";

const dictionaries = { "en-US": enUS, "zh-CN": zhCN, "zh-TW": zhTW };
interface SymbolRow {
  symbol: string;
  name: string;
  count: number;
  latest: string;
}
export function Demo({ client }: { client: PortalClient }) {
  const { locale, selection, setSelection } = usePortalLocale(client);
  return (
    <PortalAppProvider client={client} locale={locale}>
      <Symbols client={client} locale={locale} selection={selection} setLocale={setSelection} />
    </PortalAppProvider>
  );
}
function Symbols({
  client,
  locale,
  setLocale,
  selection,
}: {
  client: PortalClient;
  locale: Locale;
  selection: LocaleSelection;
  setLocale(locale: LocaleSelection): void;
}) {
  const d = dictionaries[locale],
    [query, setQuery] = useState(""),
    [items, setItems] = useState<SymbolRow[]>([]),
    [loading, setLoading] = useState(false),
    [error, setError] = useState("");
  const search = useCallback(
    async (term = "") => {
      setLoading(true);
      setError("");
      try {
        const data = await client.machine<{ items: SymbolRow[] }>(
          "GET",
          "/api/v1/symbols?limit=20" +
            (term ? "&q=" + encodeURIComponent(term) : ""),
        );
        setItems(data.items);
      } catch (e) {
        setItems([]);
        setError(
          (e as { key: string }).key === "privateOnly"
            ? d.privateOnly
            : d.unavailable,
        );
      } finally {
        setLoading(false);
      }
    },
    [client, d],
  );
  useEffect(() => {
    void search();
  }, [search]);
  return (
    <PortalPage title={d.title} description={d.description} actions={
      <PortalLocaleSelect locale={locale} selection={selection} onChange={setLocale} />
    }>
      <Flex gap={8} wrap>
        <Input
          aria-label={d.filter}
          placeholder={d.filter}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onPressEnter={() => search(query)}
          style={{ maxWidth: 360 }}
        />
        <Button type="primary" onClick={() => search(query)} loading={loading}>
          {d.search}
        </Button>
      </Flex>
      {error && <Alert type="error" role="alert" title={error} showIcon />}
      <Table
        rowKey="symbol"
        loading={loading}
        pagination={false}
        dataSource={items}
        scroll={{ x: 450 }}
        columns={(["symbol", "name", "count", "latest"] as const).map(
          (key) => ({ title: d[key], dataIndex: key }),
        )}
      />
    </PortalPage>
  );
}
