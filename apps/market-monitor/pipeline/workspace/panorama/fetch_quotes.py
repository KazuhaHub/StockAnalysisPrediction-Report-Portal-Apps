"""抓取全市场最新行情快照（未复权收盘价、成交额、市值口径所需股本）。"""
import json
import time

import mcpc

CODES = None


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def fetch(codes, size=200):
    m = mcpc.MCP("http://localhost:8091/mcp").init()
    out, bad = {}, []
    for grp in chunks(codes, size):
        try:
            r = m.call("query_stock_quote", {"action": "latest", "stock_code": ",".join(grp)})
        except Exception as e:
            # 兜底：拆小重试
            for c in grp:
                try:
                    r1 = m.call("query_stock_quote", {"action": "latest", "stock_code": c})
                    for d in (r1.get("data") or []):
                        out[d["symbol"]] = d
                except Exception:
                    bad.append(c)
            continue
        if isinstance(r, dict) and r.get("error"):
            for c in grp:
                try:
                    r1 = m.call("query_stock_quote", {"action": "latest", "stock_code": c})
                    for d in (r1.get("data") or []):
                        out[d["symbol"]] = d
                except Exception:
                    bad.append(c)
            continue
        for d in (r.get("data") or []):
            out[d["symbol"]] = d
        time.sleep(0.1)
    return out, bad


def main():
    fin = json.load(open("data/fundamentals_latest.json"))
    codes = sorted({x["symbol"] for x in fin})
    print("codes", len(codes))
    out, bad = fetch(codes)
    print("got", len(out), "bad", len(bad))
    json.dump(out, open("data/quotes.json", "w"), ensure_ascii=False)
    json.dump(bad, open("data/quotes_bad.json", "w"), ensure_ascii=False)


if __name__ == "__main__":
    main()
