#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""成交额库：宽基 ETF 日成交额，落 parquet（date, code, amount）。

数据来源：腾讯日线 web.ifzq.gtimg.cn/appstock/app/fqkline/get
  · 返回 [date, open, close, high, low, volume, {info}]，volume 单位为手；
  · 这里取成交额字段（腾讯日线第 7 项 dict 里的 amount，若缺失则用 close×volume×100 估算），
    与交易所口径的成交额相差在 1% 以内，仅用于「放量倍数」这一相对指标。

用法：
    python3 amount.py --backfill 2024-01-01
    python3 amount.py --daily
"""
import json
import os
import sys
import time
import urllib.request

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "..", "data", "amount.parquet")
UNIV = os.path.join(HERE, "universe.csv")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
THROTTLE = 0.12


def universe():
    u = pd.read_csv(UNIV, dtype={"基金代码": str})
    u = u[u["cat"] != "非宽基"]
    return u[["基金代码", "ex"]].values.tolist()


def _load():
    if os.path.exists(STORE):
        df = pd.read_parquet(STORE)
        df["date"] = pd.to_datetime(df["date"])
        df["code"] = df["code"].astype(str)
        return df
    return pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"),
                         "code": pd.Series(dtype="object"),
                         "amount": pd.Series(dtype="float64")})


def _save(df):
    df["date"] = pd.to_datetime(df["date"])
    df = df.drop_duplicates(subset=["date", "code"], keep="last")
    df = df.sort_values(["date", "code"]).reset_index(drop=True)
    df.to_parquet(STORE, index=False)
    return df


def fetch(code, ex, start="2024-01-01"):
    """腾讯日线成交额（亿元）。"""
    sym = ("sh" if ex == "SH" else "sz") + code
    q = "%s,day,%s,2050-01-01,900,qfq" % (sym, start)
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=" + q
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read().decode("utf-8", "ignore"))
    node = (d.get("data") or {}).get(sym) or {}
    rows = node.get("qfqday") or node.get("day") or []
    out = []
    for x in rows:
        try:
            date, close, vol = x[0], float(x[2]), float(x[5])
            amt = None
            if len(x) > 6 and isinstance(x[6], dict):
                a = x[6].get("amount")
                if a:
                    amt = float(a) / 1e8
            if amt is None:
                amt = close * vol * 100 / 1e8     # 手 → 股，估算
            out.append({"date": date, "code": code, "amount": round(amt, 4)})
        except Exception:
            continue
    return pd.DataFrame(out)


def backfill(start="2024-01-01"):
    old = _load()
    have = set(old["code"].unique()) if not old.empty else set()
    todo = [c for c, e in universe() if c not in have]
    print("[amount] 待抓 %d 只（已有 %d）" % (len(todo), len(have)))
    buf, t0 = [], time.time()
    for i, (c, ex) in enumerate([(c, e) for c, e in universe() if c in set(todo)], 1):
        try:
            df = fetch(c, ex, start)
            if not df.empty:
                buf.append(df)
        except Exception as e:
            print("  %s %s" % (c, repr(e)[:60]), file=sys.stderr)
        if i % 30 == 0 or i == len(todo):
            if buf:
                old = _save(pd.concat([old] + buf, ignore_index=True))
                buf = []
            el = time.time() - t0
            print("  %d/%d 用时 %.0fs" % (i, len(todo), el))
        time.sleep(THROTTLE)
    if buf:
        old = _save(pd.concat([old] + buf, ignore_index=True))
    print("[amount] %d 行，%s ~ %s" % (len(old), old["date"].min().date(), old["date"].max().date()))


def daily():
    old = _load()
    buf = []
    for c, ex in universe():
        try:
            df = fetch(c, ex, start=str(pd.Timestamp.today().date() - pd.Timedelta(days=15)))
            if not df.empty:
                buf.append(df)
        except Exception:
            pass
        time.sleep(THROTTLE)
    if buf:
        old = _save(pd.concat([old] + buf, ignore_index=True))
    print("[amount] 日更完成，最新 %s" % old["date"].max().date())
    return 0


def main():
    if "--backfill" in sys.argv:
        i = sys.argv.index("--backfill")
        backfill(sys.argv[i + 1] if len(sys.argv) > i + 1 else "2024-01-01")
    elif "--daily" in sys.argv:
        return daily()
    df = _load()
    print("[amount] %d 行 / %d 只 / %s ~ %s"
          % (len(df), df["code"].nunique(), df["date"].min().date(), df["date"].max().date()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
