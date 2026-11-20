#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""份额库：交易所披露的 ETF 份额，落 parquet 长表（date, code, shares, ex）。

数据来源与约束（实测 2026-11-13）：
  · 上交所 fund_etf_scale_sse(date) 支持任意历史日期回溯，一次返回当日全部沪市 ETF；
    但 T 日份额要 T+1 才披露（当日 16:50 查 11-13 返回空，查 11-12 正常）。
  · 深交所 fund_etf_scale_szse() 只有最新一期快照，无法回溯 —— 深市份额只能逐日累积。

用法：
    python3 shares.py --backfill 2024-01-02   # 回溯沪市历史（深市无法回溯）
    python3 shares.py --daily                 # 日更：抓当日两市快照并追加
    python3 shares.py --status                # 查看库内覆盖
"""
import os
import sys
import time
import datetime as dt

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "..", "data", "shares.parquet")
UNIV = os.path.join(HERE, "universe.csv")

# 请求节流（秒）：上交所接口对高频请求会限流
THROTTLE = 0.45


def universe():
    """宽基 ETF 池：203 只，12 类。"""
    u = pd.read_csv(UNIV, dtype={"基金代码": str})
    return u[u["cat"] != "非宽基"][["基金代码", "ex", "cat", "name"]]


def _load():
    if os.path.exists(STORE):
        df = pd.read_parquet(STORE)
        df["date"] = pd.to_datetime(df["date"])
        df["code"] = df["code"].astype(str)
        return df
    return pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"),
                         "code": pd.Series(dtype="object"),
                         "shares": pd.Series(dtype="float64"),
                         "ex": pd.Series(dtype="object")})


def _append(old, new):
    if new is None or new.empty:
        return old
    df = pd.concat([old, new], ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    df = df.drop_duplicates(subset=["date", "code"], keep="last")
    df = df.sort_values(["date", "code"]).reset_index(drop=True)
    df.to_parquet(STORE, index=False)
    return df


def fetch_sse(day):
    """上交所某日全部 ETF 份额。返回 DataFrame 或 None（无数据）。"""
    import akshare as ak
    try:
        df = ak.fund_etf_scale_sse(date=day.strftime("%Y%m%d"))
    except Exception:
        return None
    if df is None or df.empty or "基金代码" not in df.columns:
        return None
    df = df[["基金代码", "基金份额"]].copy()
    df["基金代码"] = df["基金代码"].astype(str).str.strip()
    df["基金份额"] = pd.to_numeric(df["基金份额"], errors="coerce")
    df = df.dropna(subset=["基金份额"])
    df["date"] = day
    df["ex"] = "SH"
    return df.rename(columns={"基金代码": "code", "基金份额": "shares"})[
        ["date", "code", "shares", "ex"]]


def fetch_szse(day, nav_hint=None):
    """深交所最新一期 ETF 份额。

    该接口只给快照且**不带日期**，实测返回的是最近一个已披露日的份额（T 日盘后仍为 T-1），
    因此调用方必须传入真实日期，不能直接用 today。
    若给了 nav_hint（nav.parquet 的 date→code→nav），用快照自带的净值反查日期做锚定。
    """
    import akshare as ak
    df = ak.fund_etf_scale_szse()
    if df is None or df.empty:
        return None
    df = df[["基金代码", "基金份额", "净值"]].copy()
    df["基金代码"] = df["基金代码"].astype(str).str.strip()
    df["基金份额"] = pd.to_numeric(
        df["基金份额"].astype(str).str.replace(",", "", regex=False), errors="coerce")
    df["净值"] = pd.to_numeric(df["净值"], errors="coerce")
    df = df.dropna(subset=["基金份额"])

    if nav_hint is not None:
        d = _anchor_date(df, nav_hint)
        if d is not None:
            day = d

    df["date"] = day
    df["ex"] = "SZ"
    return df.rename(columns={"基金代码": "code", "基金份额": "shares"})[
        ["date", "code", "shares", "ex"]]


def _anchor_date(sz_df, nav_hint):
    """用深交所快照里的净值反查它属于哪一天。

    nav_hint 的 index 必须已转成 datetime（parquet 里存的是字符串时尤其要注意），
    否则 recent.index 取到 str，.date() 会抛 AttributeError。
    """
    sub = sz_df.dropna(subset=["净值"])
    if sub.empty:
        return None
    recent = nav_hint.tail(8)
    if not isinstance(recent.index, pd.DatetimeIndex):
        recent = recent.copy()
        recent.index = pd.to_datetime(recent.index)
    best, best_hit = None, -1
    for d in recent.index:
        row = recent.loc[d]
        hit = tot = 0
        for _, r in sub.iterrows():
            c = str(r["基金代码"])
            if c in row.index and pd.notna(row[c]):
                tot += 1
                if abs(float(row[c]) - float(r["净值"])) < 1e-4:
                    hit += 1
        if tot >= 5 and hit > best_hit:
            best, best_hit = d, hit
    if best is None or best_hit < 5:
        return None
    return pd.Timestamp(best).date()


def trade_days(start, end):
    """交易日历（新浪）。"""
    import akshare as ak
    cal = ak.tool_trade_date_hist_sina()
    cal["trade_date"] = pd.to_datetime(cal["trade_date"])
    m = (cal["trade_date"] >= pd.Timestamp(start)) & (cal["trade_date"] <= pd.Timestamp(end))
    return [d.date() for d in cal.loc[m, "trade_date"]]


def backfill(start="2024-01-02"):
    """回溯沪市份额。深市无历史接口，只能逐日累积。"""
    old = _load()
    have = set(old.loc[old["ex"] == "SH", "date"].dt.date)
    days = trade_days(start, dt.date.today())
    todo = [d for d in days if d not in have]
    print("[shares] 沪市待回溯 %d 个交易日（已有 %d）" % (len(todo), len(have)))

    uni = universe()
    codes = set(uni.loc[uni["ex"] == "SH", "基金代码"])
    buf, n_new, t0 = [], 0, time.time()
    for i, d in enumerate(todo, 1):
        df = fetch_sse(d)
        if df is not None:
            df = df[df["code"].isin(codes)]
            if not df.empty:
                buf.append(df)
                n_new += 1
        if i % 40 == 0 or i == len(todo):
            if buf:
                old = _append(old, pd.concat(buf, ignore_index=True))
                buf = []
            el = time.time() - t0
            print("  %d/%d  已写入 %d 天  用时 %.0fs  预计剩余 %.0fs"
                  % (i, len(todo), n_new, el, el / i * (len(todo) - i)))
        time.sleep(THROTTLE)
    if buf:
        old = _append(old, pd.concat(buf, ignore_index=True))
    print("[shares] 回溯完成，库内 %d 行" % len(old))
    status()


def daily():
    """日更：抓当日两市。上交所若未披露（T 日盘后）会自动跳过沪市。"""
    old = _load()
    today = dt.date.today()
    uni = universe()
    sh_codes = set(uni.loc[uni["ex"] == "SH", "基金代码"])
    sz_codes = set(uni.loc[uni["ex"] == "SZ", "基金代码"])

    got = []
    sh_date = None
    # 上交所：T 日未披露时，向前找最近一个可取的交易日（最多回退 4 天，跨周末）
    for back in range(0, 5):
        d = today - dt.timedelta(days=back)
        if d.weekday() >= 5:
            continue
        df = fetch_sse(d)
        if df is not None and not df.empty:
            df = df[df["code"].isin(sh_codes)]
            if not df.empty:
                got.append(df)
                sh_date = d
                print("[shares] 沪市 %s：%d 只" % (d, len(df)))
                break
        time.sleep(THROTTLE)
    else:
        print("[shares] 沪市：近 5 天均无可取数据（份额未披露或接口异常）", file=sys.stderr)

    # 深交所：只有最新快照，按净值锚定真实日期（不能直接用 today）
    try:
        hint = None
        nav_p = os.path.join(HERE, "..", "data", "nav.parquet")
        if os.path.exists(nav_p):
            nv = pd.read_parquet(nav_p)
            nv["code"] = nv["code"].astype(str)
            nv["date"] = pd.to_datetime(nv["date"])
            hint = nv.pivot_table(index="date", columns="code", values="nav", aggfunc="last")
        df = fetch_szse(sh_date or today, hint)
        if df is not None and not df.empty:
            df = df[df["code"].isin(sz_codes)]
            got.append(df)
            print("[shares] 深市 %s：%d 只（净值锚定）" % (df["date"].iloc[0], len(df)))
    except Exception as e:
        print("[shares] 深市失败：%s" % e, file=sys.stderr)

    if got:
        old = _append(old, pd.concat(got, ignore_index=True))
        print("[shares] 库内 %d 行，最新 %s" % (len(old), old["date"].max().date()))
    return 0 if got else 1


def status():
    df = _load()
    if df.empty:
        print("[shares] 空库")
        return
    uni = universe()
    df = df[df["code"].isin(set(uni["基金代码"]))]
    g = df.groupby("ex")["date"].agg(["min", "max", "nunique"])
    print("[shares] 覆盖：")
    print(g.to_string())
    # 每日覆盖只数（近 5 日）
    last = df[df["date"] >= df["date"].max() - pd.Timedelta(days=10)]
    print("\n近 10 天每日只数：")
    print(last.groupby(["date", "ex"]).size().unstack(fill_value=0).tail(10).to_string())


def main():
    if "--backfill" in sys.argv:
        i = sys.argv.index("--backfill")
        start = sys.argv[i + 1] if len(sys.argv) > i + 1 else "2024-01-02"
        backfill(start)
    elif "--daily" in sys.argv:
        return daily()
    else:
        status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
