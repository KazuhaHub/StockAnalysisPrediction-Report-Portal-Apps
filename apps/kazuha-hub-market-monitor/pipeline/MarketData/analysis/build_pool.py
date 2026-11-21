# -*- coding: utf-8 -*-
"""
MarketData(parquet, 1525 只后复权) → quant-signal-research 池格式(JSON)
输出到 /tmp，不动生产目录。
"""
import sys, json, os
sys.path.insert(0, "/opt/daily-tasks/MarketData")
import numpy as np
import pandas as pd

START = sys.argv[1] if len(sys.argv) > 1 else "2020-01-01"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/tmp/klines_ohlcv_1525.json"

def suffix(code, board):
    if code.startswith("6"):
        return ".SH"
    if code.startswith(("0", "3")):
        return ".SZ"
    if code.startswith(("8", "4")):
        return ".BJ"
    return ""

meta_all = json.load(open("/opt/daily-tasks/MarketData/meta.json"))["stocks"]

frames = []
for y in range(int(START[:4]), 2027):
    p = f"/opt/daily-tasks/MarketData/bars/{y}.parquet"
    if not os.path.exists(p):
        continue
    d = pd.read_parquet(p)
    d = d[d["date"] >= START]
    if len(d):
        frames.append(d)
df = pd.concat(frames, ignore_index=True)
print("rows", df.shape, df["code"].nunique(), "codes", df["date"].min(), "~", df["date"].max(), flush=True)

out = {"_meta": {
    "adjust": "hfq",
    "source": "~/MarketData (stock-server query_stock_quote adjust=hfq)",
    "includes_delisted": False,
    "built_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
    "note": "后复权；v 单位为股；真实成交价 = close / factor（factor 未入池）",
    "start": START,
}}
n_bar = 0
for code, g in df.groupby("code", sort=True):
    g = g.sort_values("date")
    info = meta_all.get(code, {})
    sfx = suffix(code, info.get("board"))
    if not sfx:
        continue
    bars = []
    for r in g.itertuples(index=False):
        if not np.isfinite(r.close) or r.close <= 0:
            continue
        bars.append({"d": r.date, "o": round(float(r.open), 4),
                     "c": round(float(r.close), 4),
                     "h": round(float(r.high), 4),
                     "l": round(float(r.low), 4),
                     "v": round(float(r.volume), 1)})
    if len(bars) < 250:
        continue
    out[code + sfx] = {"name": info.get("name", ""), "src": "marketdata_hfq", "bars": bars}
    n_bar += len(bars)

with open(OUT, "w") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
sz = os.path.getsize(OUT) / 1e6
print(f"saved {OUT}  stocks={len(out)-1}  bars={n_bar}  {sz:.0f} MB  {sz*1e6/max(n_bar,1):.0f} bytes/bar")
