# -*- coding: utf-8 -*-
"""融资盘日线的来源链：MarketData 行情库 → 腾讯 → 新浪，全部在覆盖率闸门之前跑完。

为什么不再请求东财 push2his：生产机的出口 IP 被东财限流/拒连（2026-11-24 那次
1529/4173 只就是这么来的），而同一台机器上 marketdata 任务每晚已经把全市场日线
存进了本地行情库（后复权 + 复权因子），没有理由再去外网重抓一遍。

口径换算（行情库 → 本表的前复权口径，见 MarketData/market_data.py 与
stock_server 的 _attach_quote_normalization）：
  - 行情库 close 为后复权价 = 真实价 × factor_t
  - 前复权价（锚定到目标日 T）= 后复权价 / factor_T —— 与东财 fqt=1 截止到 T 的序列一致
  - 行情库 volume = 真实股数 / factor_t；本表 volume 为手 → volume × factor_t / 100
  - amount 两边都是真实成交额（元），原样
  - tradestatus=0（停牌）的行丢掉：东财日线不含停牌日

每只票取到的序列都要和本地旧表对一次口：重叠交易日上 新/旧 收盘价之比必须是
同一个常数（无除权时≈1；期间有除权时旧表锚点过期，比值是另一个常数），且成交额
一致（看最近 20 个重叠日）。对不上就不用这只票的库内数据，交给下一个来源。腾讯、新浪两个备用源沿用
analysis/fill_bars_tx.py、fill_bars_sina.py 原有的「参照日收盘对口」安全阀。
"""
import glob
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

COLS = ["code", "date", "open", "close", "high", "low", "volume", "amount"]
TOL = 0.5            # 百分比
# 对口用的重叠交易日数。只看最近一段：东财/腾讯的前复权是「减法」（每次除权减去
# 分红），行情库换算出的是「比例」前复权，两者之比在一个除权段内会漂 0.3–0.8%，
# 拿 150 天全窗口比会把半年内派过息的票成批拒掉；20 天内一般没有除权，比值恒定。
OVERLAP = 20
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def _log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def md_home():
    return os.environ.get("MD_HOME") or os.path.join(os.path.expanduser("~"), "MarketData")


# ---------------------------------------------------------------- 行情库
def from_marketdata(codes, target, limit, home=None):
    """行情库里每只票截止到 target 的最近 limit 根已交易日线，换算成前复权口径。
    target 当天没有已交易 bar 的票不返回（交给备用源）。"""
    bars = os.path.join(home or md_home(), "bars")
    years = sorted(glob.glob(os.path.join(bars, "*.parquet")))
    # limit 根交易日不会跨过两个以上的自然年
    want = {str(int(target[:4]) - k) for k in range(0, 2 + limit // 240)}
    files = [p for p in years if os.path.basename(p)[:4] in want]
    if not files or not codes:
        return pd.DataFrame(columns=COLS)
    import pyarrow.dataset as ds
    expr = (ds.field("date") <= target) & ds.field("code").isin(sorted(set(codes)))
    df = ds.dataset(files, format="parquet").to_table(filter=expr).to_pandas()
    if df.empty:
        return pd.DataFrame(columns=COLS)
    # 停牌日不进表（东财日线不含停牌日）：行情库写入时 tradestatus 会被兜底成 1，
    # 所以再看成交量/成交额。重复的 (code, date) 只留一行。
    df = df[(df["tradestatus"] == 1) & (df["factor"] > 0) & (df["volume"] > 0) & (df["amount"] > 0)]
    df = df.drop_duplicates(["code", "date"], keep="last")
    anchor = df[df["date"] == target].set_index("code")["factor"]
    df = df[df["code"].isin(anchor.index)]
    if df.empty:
        return pd.DataFrame(columns=COLS)
    df = df.sort_values(["code", "date"]).groupby("code", sort=False).tail(limit)
    ft = df["code"].map(anchor)
    out = pd.DataFrame({
        "code": df["code"], "date": df["date"],
        "open": df["open"] / ft, "close": df["close"] / ft,
        "high": df["high"] / ft, "low": df["low"] / ft,
        "volume": df["volume"] * df["factor"] / 100.0,
        "amount": df["amount"].astype(float),
    })
    return out[COLS].reset_index(drop=True)


def consistent(new, old, tol=TOL):
    """一只票的新序列与本地旧表对口：重叠日上收盘价比值恒定、成交额一致。"""
    if old is None or old.empty:
        return True
    m = new.merge(old, on="date", suffixes=("_n", "_o"))
    m = m[(m["close_o"] > 0)].sort_values("date").tail(OVERLAP)
    if m.empty:
        return True
    r = m["close_n"] / m["close_o"]
    med = float(r.median())
    if not (0.2 <= med <= 1 + tol / 100.0):       # 除权只会让旧锚点之前的价往下调
        return False
    if float((r / med - 1).abs().max()) * 100 > tol:
        return False
    a = m[(m["amount_o"] > 0) & (m["amount_n"] > 0)]
    if len(a) and float((a["amount_n"] / a["amount_o"] - 1).abs().median()) * 100 > tol:
        return False
    return True


# ---------------------------------------------------------------- 腾讯
def _tx_market(code):
    if code[0] in "569":
        return "sh"
    if code[0] in "48":
        return "bj"
    return "sz"


def tx_daily(code, count=40):
    """腾讯 qfq 日线：{date: (open, close, high, low, volume 手, amount 元)}；失败返回 None。

    用 newfqkline（与 fqkline 同主机）：它多带成交额（第 9 列，万元）。成交量
    主板/创业板/场内基金为手，科创板（688/689）为股，统一换成手。"""
    import requests
    mkt = _tx_market(code)
    url = "https://web.ifzq.gtimg.cn/appstock/app/newfqkline/get"
    per_lot = 100.0 if code.startswith(("688", "689")) else 1.0
    for a in range(3):
        try:
            r = requests.get(url, params={"param": "%s%s,day,,,%d,qfq" % (mkt, code, count)},
                             timeout=8, headers=UA)
            d = r.json().get("data", {}).get(mkt + code, {})
            k = d.get("qfqday") or d.get("day") or []
            if not k:
                return None
            return {x[0]: (float(x[1]), float(x[2]), float(x[3]), float(x[4]),
                           float(x[5]) / per_lot, float(x[8]) * 10000.0)
                    for x in k if len(x) > 8}
        except Exception:
            time.sleep(0.2 * (a + 1))
    return None


def from_tx(codes, target, prev, prevd, workers=6, tol=TOL):
    """腾讯补 target 当天；参照日 prev 的收盘与成交额都必须与本地一致（偏差 ≤ tol%）。
    prevd: DataFrame(index=code, columns=[close, amount])。返回 (recs, 拒绝数)。"""
    recs, bad = [], 0
    codes = [c for c in codes if c in prevd.index]
    if not codes:
        return recs, bad
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(tx_daily, c): c for c in codes}
        for f in as_completed(futs):
            c = futs[f]
            m = f.result()
            if not m or target not in m or prev not in m:
                continue
            ref = m[prev]
            local_close, local_amt = prevd.loc[c, "close"], prevd.loc[c, "amount"]
            dclose = abs(ref[1] / local_close - 1) * 100 if local_close else 100.0
            damt = abs(ref[5] / local_amt - 1) * 100 if local_amt and ref[5] else 0.0
            if max(dclose, damt) > tol:
                bad += 1
                continue
            o, cl, hi, lo, vol, amt = m[target]
            if not amt:
                continue
            recs.append((c, target, o, cl, hi, lo, vol, amt))
    return recs, bad


# ---------------------------------------------------------------- 新浪
def _sina_market(code):
    return "sh" if code[0] in "569" else ("bj" if code[0] in "48" else "sz")


def sina_daily(code, start, end):
    """新浪 qfq 日线（个股 stock_zh_a_daily，场内基金 fund_etf_hist_sina）；
    volume 为股、amount 为元。失败返回 None。"""
    import akshare as ak
    is_fund = code[0] in "15"
    for a in range(3):
        try:
            if is_fund:
                df = ak.fund_etf_hist_sina(symbol=_sina_market(code) + code)
            else:
                df = ak.stock_zh_a_daily(symbol=_sina_market(code) + code,
                                         start_date=start.replace("-", ""),
                                         end_date=end.replace("-", ""), adjust="qfq")
            if df is None or not len(df):
                return None
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            return df[(df["date"] >= start) & (df["date"] <= end)]
        except Exception:
            time.sleep(0.3 * (a + 1))
    return None


def from_sina(codes, target, prev, prevd, workers=4, tol=TOL):
    """新浪补 target 当天；参照日 prev 的收盘与成交额都必须与本地一致。
    prevd: DataFrame(index=code, columns=[close, amount])。返回 (recs, 拒绝数)。"""
    recs, bad = [], 0
    codes = [c for c in codes if c in prevd.index]
    if not codes:
        return recs, bad
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(sina_daily, c, prev, target): c for c in codes}
        for f in as_completed(futs):
            c = futs[f]
            df = f.result()
            if df is None:
                continue
            rrow, trow = df[df["date"] == prev], df[df["date"] == target]
            if not len(rrow) or not len(trow):
                continue
            dclose = abs(rrow.iloc[-1]["close"] / prevd.loc[c, "close"] - 1) * 100
            damt = (abs(rrow.iloc[-1]["amount"] / prevd.loc[c, "amount"] - 1) * 100
                    if prevd.loc[c, "amount"] else 0.0)
            if max(dclose, damt) > tol:
                bad += 1
                continue
            r = trow.iloc[-1]
            recs.append((c, target, float(r["open"]), float(r["close"]), float(r["high"]),
                         float(r["low"]), float(r["volume"]) / 100.0, float(r["amount"])))
    return recs, bad


# ---------------------------------------------------------------- 来源链
def collect(codes, old, target, limit, home=None):
    """按 行情库 → 腾讯 → 新浪 给 codes 取日线（截止 target）。
    返回 (new DataFrame, {"marketdata": n, "tx": n, "sina": n, "missing": n})。"""
    codes = sorted(set(codes))
    old = old if len(old) else pd.DataFrame(columns=COLS)
    md = from_marketdata(codes, target, limit, home)
    parts, got, md_bad = [], set(), 0
    if len(md):
        old_by = {c: g for c, g in old[old["date"] < target].groupby("code")}
        for c, g in md.groupby("code"):
            if consistent(g, old_by.get(c)):
                parts.append(g)
                got.add(c)
            else:
                md_bad += 1
    mix = {"marketdata": len(got), "tx": 0, "sina": 0, "missing": 0}

    rest = [c for c in codes if c not in got]
    prev_dates = sorted(d for d in old["date"].unique() if d < target)
    if rest and prev_dates:
        prev = prev_dates[-1]
        prevd = old[old["date"] == prev].drop_duplicates("code", keep="last").set_index("code")[["close", "amount"]]
        tx, tx_bad = from_tx(rest, target, prev, prevd)
        mix["tx"] = len(tx)
        parts.append(pd.DataFrame(tx, columns=COLS))
        done = {r[0] for r in tx}
        rest = [c for c in rest if c not in done]
        sina, sina_bad = from_sina(rest, target, prev, prevd)
        mix["sina"] = len(sina)
        parts.append(pd.DataFrame(sina, columns=COLS))
        done = {r[0] for r in sina}
        rest = [c for c in rest if c not in done]
        if tx_bad or sina_bad:
            _log("  备用源口径不符（不写入）：腾讯 %d，新浪 %d" % (tx_bad, sina_bad))
    if md_bad:
        _log("  行情库与本地旧表对不上口（改用备用源）：%d 只" % md_bad)
    mix["missing"] = len(rest)
    parts = [p for p in parts if len(p)]
    new = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=COLS)
    return new, mix
