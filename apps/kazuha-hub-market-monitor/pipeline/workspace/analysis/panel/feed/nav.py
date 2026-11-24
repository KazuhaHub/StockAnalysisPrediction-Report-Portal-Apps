#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""净值库：ETF 单位净值，落 parquet 长表（date, code, nav）。

数据来源：天天基金历史净值 api.fund.eastmoney.com/f10/lsjz
  · 每只一个请求，pageSize 给大值可一次取全历史；实测 510300 2026-11-12 单位净值 4.1203，
    与「份额变化 × 净值 = 净流入」反推的隐含值一致，可作为口径验证锚点。
  · 场外净值 T 日晚间更新；ETF 单位净值通常 T+1 可取，日更时按 code 增量拉最近一段即可。

用法：
    python3 nav.py --backfill 2024-01-01   # 回溯全部宽基 ETF 历史净值
    python3 nav.py --daily                 # 日更：只拉最近 20 条
    python3 nav.py --status
"""
import os
import sys
import time

import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "..", "data", "nav.parquet")
UNIV = os.path.join(HERE, "universe.csv")

URL = "https://api.fund.eastmoney.com/f10/lsjz"
HEAD = {"Referer": "https://fundf10.eastmoney.com/",
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")}
THROTTLE = 0.25


def universe():
    u = pd.read_csv(UNIV, dtype={"基金代码": str})
    return u[u["cat"] != "非宽基"]["基金代码"].tolist()


def _load():
    if os.path.exists(STORE):
        df = pd.read_parquet(STORE)
        df["date"] = pd.to_datetime(df["date"])
        df["code"] = df["code"].astype(str)
        return df
    return pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"),
                         "code": pd.Series(dtype="object"),
                         "nav": pd.Series(dtype="float64")})


def _save(df):
    df["date"] = pd.to_datetime(df["date"])
    df["code"] = df["code"].astype(str)
    df = df.drop_duplicates(subset=["date", "code"], keep="last")
    df = df.sort_values(["date", "code"]).reset_index(drop=True)
    df.to_parquet(STORE, index=False)
    return df


def fetch(code, max_pages=400, stop_before=None):
    """单只 ETF 历史单位净值。

    东财 f10/lsjz 的 pageSize 被服务端强制为 20（传更大值返回空），必须翻页；
    按时间倒序返回，所以取到 stop_before 之前的日期即可停。
    """
    rows, page = [], 1
    while page <= max_pages:
        r = requests.get(URL, params={"fundCode": code, "pageIndex": page,
                                      "pageSize": 20},
                         headers=HEAD, timeout=20)
        try:
            lst = (r.json().get("Data") or {}).get("LSJZList") or []
        except Exception:
            break
        if not lst:
            break
        rows.extend(lst)
        oldest = lst[-1].get("FSRQ") or ""
        if stop_before and oldest and oldest < stop_before:
            break
        if len(lst) < 20:
            break
        page += 1
        time.sleep(0.08)
    out = []
    for x in rows:
        try:
            out.append({"date": x["FSRQ"], "code": code, "nav": float(x["DWJZ"])})
        except Exception:
            continue
    return pd.DataFrame(out)


def backfill(start="2024-01-01"):
    old = _load()
    have = set(old["code"].unique()) if not old.empty else set()
    codes = universe()
    todo = [c for c in codes if c not in have]
    print("[nav] 待抓 %d 只（已有 %d）" % (len(todo), len(have)))
    buf, t0 = [], time.time()
    for i, c in enumerate(todo, 1):
        try:
            df = fetch(c, stop_before=start)
            if not df.empty:
                buf.append(df)
        except Exception as e:
            print("  %s 失败 %s" % (c, repr(e)[:80]), file=sys.stderr)
        if i % 25 == 0 or i == len(todo):
            if buf:
                old = _save(pd.concat([old] + buf, ignore_index=True))
                buf = []
            el = time.time() - t0
            print("  %d/%d 用时 %.0fs 剩余 %.0fs" % (i, len(todo), el, el / i * (len(todo) - i)))
        time.sleep(THROTTLE)
    if buf:
        old = _save(pd.concat([old] + buf, ignore_index=True))
    old = old[old["date"] >= pd.Timestamp(start)]
    _save(old)
    print("[nav] 完成，%d 行，%s ~ %s" % (len(old), old["date"].min().date(), old["date"].max().date()))


def daily():
    """日更：只补最近一段。"""
    old = _load()
    codes = universe()
    last = old.groupby("code")["date"].max() if not old.empty else pd.Series(dtype="datetime64[ns]")
    buf = []
    for i, c in enumerate(codes, 1):
        try:
            # 一页 20 条（约 4 周）；应用停过几周时多翻几页，把缺口补上
            seen = last.get(c)
            gap_days = (pd.Timestamp.today() - seen).days if seen is not None and pd.notna(seen) else 28
            df = fetch(c, max_pages=min(6, 1 + gap_days // 28))
            if not df.empty:
                buf.append(df)
        except Exception as e:
            print("  %s 失败 %s" % (c, repr(e)[:60]), file=sys.stderr)
        time.sleep(THROTTLE)
    if buf:
        old = _save(pd.concat([old] + buf, ignore_index=True))
    print("[nav] 日更完成，最新 %s" % old["date"].max().date())
    return 0


def status():
    df = _load()
    if df.empty:
        print("[nav] 空库")
        return
    print("[nav] %d 行 / %d 只 / %s ~ %s"
          % (len(df), df["code"].nunique(), df["date"].min().date(), df["date"].max().date()))


def main():
    if "--backfill" in sys.argv:
        i = sys.argv.index("--backfill")
        backfill(sys.argv[i + 1] if len(sys.argv) > i + 1 else "2024-01-01")
    elif "--daily" in sys.argv:
        return daily()
    else:
        status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
