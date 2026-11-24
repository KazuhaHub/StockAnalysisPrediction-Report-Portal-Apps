"""Minimal MCP streamable-HTTP client for the local stock-server (SERVER_URL).

不给外部包依赖，只用标准库 + requests（本机已有）。
用法：
    from mcpc import MCP
    m = MCP(SERVER_URL)
    m.init()
    r = m.call("query_financial_pit", {"action": "cross_section", "as_of": "20261113", "limit": 2000})
"""
import json
import os
import time

import requests

# The job entry starts the data server on 127.0.0.1 and exports its URL
# (STOCK_SERVER_URL). Not "localhost": resolving that name depends on the
# container's hosts file, and when it goes to DNS instead the request fails
# with a ConnectionError before reaching the server.
SERVER_URL = os.environ.get("STOCK_SERVER_URL", "http://127.0.0.1:8091/mcp")


class MCP:
    def __init__(self, url, headers=None, timeout=300):
        self.url = url
        self.timeout = timeout
        self.s = requests.Session()
        self.sid = None
        self.h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if headers:
            self.h.update(headers)
        self._id = 0

    def _post(self, payload):
        h = dict(self.h)
        if self.sid:
            h["Mcp-Session-Id"] = self.sid
        r = self.s.post(self.url, headers=h, json=payload, timeout=self.timeout)
        sid = r.headers.get("mcp-session-id")
        if sid:
            self.sid = sid
        txt = r.content.decode("utf-8", "replace")
        # SSE：按空行切成 event，同一 event 内多行 data 用 \n 拼接（长响应会跨行）
        events, buf = [], []
        for line in txt.splitlines():
            if line.strip() == "":
                if buf:
                    events.append("\n".join(buf))
                    buf = []
            elif line.startswith("data:"):
                buf.append(line[5:].lstrip())
        if buf:
            events.append("\n".join(buf))
        if events:
            return json.loads(events[-1])
        return json.loads(txt) if txt.strip() else {}

    def init(self):
        self._id += 1
        self._post({
            "jsonrpc": "2.0", "id": self._id, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "panorama", "version": "1.0"}},
        })
        h = dict(self.h)
        h["Mcp-Session-Id"] = self.sid
        self.s.post(self.url, headers=h, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, timeout=30)
        return self

    def call(self, name, args, retries=3, backoff=2.0):
        for k in range(retries):
            try:
                self._id += 1
                r = self._post({"jsonrpc": "2.0", "id": self._id, "method": "tools/call",
                                "params": {"name": name, "arguments": args}})
                if "error" in r:
                    raise RuntimeError(f"{name} error: {r['error']}")
                res = r["result"]
                if res.get("isError"):
                    raise RuntimeError(f"{name} tool error: {res}")
                cont = res.get("content") or []
                txt = "".join(c.get("text", "") for c in cont if c.get("type") == "text")
                if res.get("structuredContent"):
                    return res["structuredContent"]
                try:
                    return json.loads(txt)
                except Exception:
                    return txt
            except Exception as e:
                if k == retries - 1:
                    raise
                time.sleep(backoff * (k + 1))


if __name__ == "__main__":
    m = MCP(SERVER_URL).init()
    print(json.dumps(m.call("query_trading_calendar", {"action": "latest"}) if True else {}, ensure_ascii=False)[:400])
