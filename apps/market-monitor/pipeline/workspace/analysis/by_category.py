"""分类事件研究：不同宽基的净流入，后续收益是否不同（护盘型 vs 追涨型）。
broadData 仅 2026 年以来 207 个交易日，样本有限，结论按"方向"而非"精确值"使用。
"""
import json
import numpy as np
import pandas as pd

OUT = "/opt/daily-tasks/workspace/analysis/out"
D = json.load(open("/tmp/islands.json"))
Q = json.load(open(f"{OUT}/quotes.json"))

MAP = {"沪深300": "sh000300", "上证50": "sh000001", "中证500": "sh000905",
       "中证1000": "sh000852", "科创50": "sh000688", "创业板指": "sz399006"}
# 上证50 指数用 sh000016，先补
import urllib.request


def fetch(code, start="2025-12-01", end="2026-11-20", n=400):
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
           f"param={code},day,{start},{end},{n},qfq")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    d = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    node = d["data"][code]
    rows = node.get("qfqday") or node.get("day")
    return pd.DataFrame([{"date": x[0], "open": float(x[1]), "close": float(x[2])}
                         for x in rows]).set_index("date")


P = {k: pd.DataFrame(Q[v]["bars"]).set_index("date")[["open", "close"]] for k, v in MAP.items()}
P["上证50"] = fetch("sh000016")[["open", "close"]]

b = D["broadData"]
flow = pd.DataFrame(b["series"], index=b["dates"])


def ev(flow_col, price, thr, h, direction=1):
    """净流入超阈值 -> 次日开盘买，持有 h 日"""
    f = flow[flow_col]
    px = P[price]
    f = f[f.index.isin(px.index)]
    fwd = (px["close"].shift(-h) / px["open"].shift(-1) - 1) * 100
    sig = (f > thr) if direction > 0 else (f < -thr)
    r = fwd.reindex(f.index)[sig.reindex(f.index)].dropna()
    base = fwd.reindex(f.index).dropna()
    return len(r), r.mean(), (r > 0).mean() * 100, base.mean(), base.mean() and 0


rows = []
for cat, px in MAP.items():
    f = flow[cat]
    for thr in (30, 50, 100):
        m = f > thr
        for h in (5, 10, 20):
            pf = P[cat if cat in P else px]
            p2 = P[cat]["close"] if cat in P else None
            if p2 is None:
                continue
            fwd = (p2.shift(-h) / P[cat]["open"].shift(-1) - 1) * 100
            fwd = fwd.reindex(f.index.intersection(fwd.index)).dropna()
            sig = m.reindex(fwd.index).fillna(False)
            r = fwd[sig]
            if len(r) < 5:
                continue
            t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))
            rows.append({"分类": cat, "阈值": f">{thr}亿", "h": h, "n": len(r),
                         "均值%": round(r.mean(), 2), "胜率%": round((r > 0).mean() * 100, 0),
                         "基准%": round(fwd.mean(), 2),
                         "超额pp": round(r.mean() - fwd.mean(), 2),
                         "t": round(t, 2)})

res = pd.DataFrame(rows).sort_values(["分类", "h"])
pd.set_option("display.width", 250)
print("=== 分类净流入 → 该指数后续收益（2026-01 起，样本仅约207日）===")
print(res.to_string(index=False))
res.to_csv(f"{OUT}/by_category.csv", index=False, encoding="utf-8-sig")

# 沪深300 流入的"反向"— 全年流出
print("\n=== 沪深300 净流出后的表现（赎回潮是否意味着后续上涨） ===")
f = flow["沪深300"]
px = P["沪深300"]
for thr in (-50, -100, -200):
    for h in (5, 20):
        fwd = (px["close"].shift(-h) / px["open"].shift(-1) - 1) * 100
        common = f.index.intersection(fwd.dropna().index)
        sig = (f.reindex(common) < thr)
        r = fwd.reindex(common)[sig].dropna()
        if len(r) >= 5:
            print(f"沪深300 <{thr}亿 h={h}: n={len(r):2d} 均值{r.mean():+.2f}% "
                  f"胜率{(r>0).mean()*100:.0f}% 基准{fwd.reindex(common).mean():+.2f}%")

# 10月以来个股指数表现
print("\n=== 2026-10-01 以来各指数涨跌 ===")
for c, px in P.items():
    s = px.loc[px.index >= "2026-09-30", "close"]
    if len(s) > 2:
        print(f"{c:8s} {s.iloc[0]:9.1f} -> {s.iloc[-1]:9.1f}  {(s.iloc[-1]/s.iloc[0]-1)*100:+.2f}%")
