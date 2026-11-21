#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行情层：只抓实时报价与上证分时，落 data/latest.json。

净流入、份额、净值、成交额、两融全部由 feed/ 下的自建模块提供，本文件不再访问任何第三方看板。

用法：
    python3 quotes.py
"""
import json
import os
import sys
import urllib.request
import datetime as dt

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
UNIV = os.path.join(HERE, "feed", "universe.csv")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def _req(url, timeout=20):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_quotes(codes):
    """腾讯批量报价。返回 [{code,name,price,prev,pct,amount_yi}]。"""
    if not codes:
        return []
    qs = ",".join(("sh" if c[0] in "56" else "sz") + c for c in codes)
    raw = _req("https://qt.gtimg.cn/q=" + qs).decode("gbk", "ignore")
    rows = []
    for line in raw.strip().split(";"):
        line = line.strip()
        if not line.startswith("v_"):
            continue
        f = line.split("=", 1)[1].strip('"').split("~")
        if len(f) < 40:
            continue
        try:
            rows.append({"code": f[2], "name": f[1],
                         "price": float(f[3]), "prev": float(f[4]),
                         "pct": float(f[32]),
                         "amount_yi": round(float(f[37]) / 10000.0, 2),
                         "time": f[30]})
        except Exception:
            continue
    return rows


def fetch_index_minute(code="sh000001"):
    raw = _req("https://web.ifzq.gtimg.cn/appstock/app/minute/query?code=" + code)
    d = json.loads(raw.decode("utf-8", "ignore"))
    node = d.get("data", {}).get(code, {})
    inner = node.get("data") if isinstance(node.get("data"), dict) else {}
    day = inner.get("date") or node.get("date") or ""
    rows = [r for r in (inner.get("data") or node.get("data") or []) if isinstance(r, str)]
    times, prices, amt = [], [], []
    for r in rows:
        p = r.split()
        if len(p) < 4:
            continue
        times.append("%s:%s" % (p[0][:2], p[0][2:]))
        prices.append(float(p[1]))
        amt.append(round(float(p[3]) / 1e8, 2))
    return {"code": code, "date": day, "times": times, "prices": prices, "amount_yi": amt}


def main():
    codes = []
    if os.path.exists(UNIV):
        u = pd.read_csv(UNIV, dtype={"基金代码": str})
        codes = u[u["cat"] != "非宽基"]["基金代码"].tolist()

    path = os.path.join(DATA, "latest.json")
    old = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}

    quotes, minute, err = [], {}, ""
    try:
        quotes = fetch_quotes(codes)
    except Exception as e:
        err = "报价失败: %s" % e
        print("[quotes] " + err, file=sys.stderr)
    try:
        minute = fetch_index_minute()
    except Exception as e:
        err += " 分时失败: %s" % e
        print("[quotes] 分时失败: %s" % e, file=sys.stderr)

    payload = {
        "quotes": quotes or old.get("quotes", []),
        "index_minute": minute or old.get("index_minute", {}),
        "fetched_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "state": {"live": "ok" if quotes else "fail", "err": err},
    }
    json.dump(payload, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    print("[quotes] 报价 %d 只，分时 %d 点，%s"
          % (len(payload["quotes"]), len(minute.get("times", [])), payload["fetched_at"]))
    return 0 if quotes else 1


if __name__ == "__main__":
    sys.exit(main())
