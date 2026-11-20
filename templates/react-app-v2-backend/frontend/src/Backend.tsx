import { useEffect, useState } from "react";
import { Alert, Descriptions, Spin } from "antd";
import { useAppBackend } from "@portal-app/sdk/root-v2";

export type Hello = { greeting: string; role: string };

export type BackendCopy = {
  backendTitle: string;
  backendUnavailable: string;
  backendFailed: string;
  backendHello: string;
  backendRole: string;
};

/**
 * Reads the example route of the app's own backend. Portal relays the call to
 * the container and signs the current viewer into it; the app never builds a
 * URL, header or identity. See docs/backend-service-v2.md.
 */
export function BackendHello({ copy }: { copy: BackendCopy }) {
  const { ready, available, request } = useAppBackend();
  const [data, setData] = useState<Hello | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!ready) return;
    const abort = new AbortController();
    setFailed(false);
    request({ method: "GET", path: "/v1/hello", body: "" }, abort.signal)
      .then((result) => {
        if (abort.signal.aborted) return;
        if (result.status === 200) setData(JSON.parse(result.body) as Hello);
        else setFailed(true);
      })
      .catch(() => {
        if (!abort.signal.aborted) setFailed(true);
      });
    return () => abort.abort();
  }, [ready, request]);
  if (!available)
    return <Alert type="warning" title={copy.backendUnavailable} />;
  if (failed) return <Alert type="error" title={copy.backendFailed} />;
  if (!ready || data === null) return <Spin />;
  return (
    <Descriptions
      title={copy.backendTitle}
      size="small"
      column={1}
      items={[
        { key: "hello", label: copy.backendHello, children: data.greeting },
        { key: "role", label: copy.backendRole, children: data.role },
      ]}
    />
  );
}
