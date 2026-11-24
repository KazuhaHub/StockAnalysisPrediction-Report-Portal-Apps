#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
两融（融资盘）压力扫描 —— 数据抓取层

数据源：
  1. 沪深交易所两融个股明细（akshare stock_margin_detail_sse / _szse）  日频，T+1 披露
  2. 全市场快照（akshare stock_zh_a_spot_em）  仅 name 表/兜底，低频校准用 --refresh-spot
  3. 个股前复权日线：本地 MarketData 行情库（marketdata 任务维护）→ 腾讯 → 新浪
     （bar_sources.py）。东财 push2his 对本机出口限流/拒连，日更不再请求它。
  4. 两融账户统计（akshare stock_margin_account_info）                   平均维持担保比例

流通市值不再来自每日快照：data/float_shares.parquet 存流通股本底表，
build_data 按 fcap_T = fcap_base × close_T / close_base 由日线推算。
spot 的 price 在 09:01 盘前抓时全为 NaN，历史上唯一有用的只有 fcap 一列。
日更因此完全不请求东财 clist，避开开盘前翻页限流。

输出统一落到 data/ 下 parquet，支持增量与断点续爬。
解释器：/opt/daily-tasks/venv/bin/python3 （3.9 带 pandas + pyarrow）
"""
import os
import sys
import time
import json
import warnings
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings("ignore")

import pandas as pd
import requests

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
DATA.mkdir(parents=True, exist_ok=True)

HIST_DAYS = 121          # 回看交易日数（约半年）
BAR_LIMIT = 150          # 日线根数（多留一些用于周/月K聚合）
WORKERS_MARGIN = 4
WORKERS_BARS = 8
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


# ---------------------------------------------------------------- 交易日历
def get_trade_dates(n=HIST_DAYS):
    import akshare as ak
    cal = ak.tool_trade_date_hist_sina()
    cal["trade_date"] = pd.to_datetime(cal["trade_date"])
    today = pd.Timestamp.now().normalize()
    d = cal[cal["trade_date"] <= today]["trade_date"].sort_values()
    return [x.strftime("%Y%m%d") for x in d.tail(n)]


# ---------------------------------------------------------------- 两融明细
def _fetch_one_day_margin(date):
    """返回 (date, DataFrame) ；失败返回 (date, None)"""
    import akshare as ak
    frames = []
    for attempt in range(3):
        try:
            sh = ak.stock_margin_detail_sse(date=date)
            if sh is not None and len(sh):
                frames.append(sh.rename(columns={
                    "标的证券代码": "code", "标的证券简称": "name",
                    "融资余额": "rz", "融资买入额": "rz_buy", "融资偿还额": "rz_repay",
                    "融券余量": "rq_vol", "融券卖出量": "rq_sell", "融券偿还量": "rq_repay",
                })[["code", "name", "rz", "rz_buy", "rz_repay", "rq_vol"]])
            else:
                return date, None
            break
        except Exception:
            time.sleep(1.2 * (attempt + 1))
    else:
        return date, None

    for attempt in range(3):
        try:
            sz = ak.stock_margin_detail_szse(date=date)
            if sz is not None and len(sz):
                frames.append(sz.rename(columns={
                    "证券代码": "code", "证券简称": "name",
                    "融资余额": "rz", "融资买入额": "rz_buy",
                    "融券余量": "rq_vol",
                })[["code", "name", "rz", "rz_buy", "rq_vol"]])
                # 深市无融资偿还额，用 余额差分 反推（在计算层处理）
                frames[-1]["rz_repay"] = pd.NA
            else:
                return date, None
            break
        except Exception:
            time.sleep(1.2 * (attempt + 1))
    else:
        return date, None

    df = pd.concat(frames, ignore_index=True)
    df["date"] = date
    df["code"] = df["code"].astype(str).str.zfill(6)
    for c in ["rz", "rz_buy", "rz_repay", "rq_vol"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return date, df


def fetch_margin(dates):
    cache = DATA / "margin_hist.parquet"
    old = pd.read_parquet(cache) if cache.exists() else pd.DataFrame()
    have = set(old["date"].unique()) if len(old) else set()
    todo = [d for d in dates if d not in have]
    log("两融明细：交易日 %d 个，已缓存 %d，待抓 %d" % (len(dates), len(have), len(todo)))

    rows = []
    if todo:
        with ThreadPoolExecutor(max_workers=WORKERS_MARGIN) as ex:
            futs = {ex.submit(_fetch_one_day_margin, d): d for d in todo}
            done = 0
            for f in as_completed(futs):
                d, df = f.result()
                done += 1
                if df is not None and len(df):
                    rows.append(df)
                if done % 10 == 0 or done == len(todo):
                    log("  两融进度 %d/%d" % (done, len(todo)))
    if rows:
        new = pd.concat(rows, ignore_index=True)
        out = pd.concat([old, new], ignore_index=True) if len(old) else new
    else:
        out = old
    out = out.drop_duplicates(subset=["date", "code"], keep="last").sort_values(["date", "code"])
    out.to_parquet(cache, index=False)
    log("两融明细落盘：%d 行，%d 个交易日" % (len(out), out["date"].nunique()))
    return out


# ---------------------------------------------------------------- 全市场快照
def fetch_spot(force=False):
    """全市场快照：只作为 name 表与 fcap 兜底，日更不再强依赖。

    2026-11-12 起 fcap 由 data/float_shares.parquet 底表按日线推算，
    每天抓 59 页 clist 已无必要；而开盘前该接口翻页必被限流断连，
    是当天整条流水线崩掉的直接原因。底表存在且本地快照未过期(<7天)时
    直接复用，不发任何请求。需要校准股本时显式跑 --refresh-spot。
    """
    import akshare as ak
    cache = DATA / "spot.parquet"
    fs = DATA / "float_shares.parquet"
    if not force and fs.exists() and cache.exists():
        age_h = (time.time() - cache.stat().st_mtime) / 3600.0
        if age_h < 24 * 7:
            df = pd.read_parquet(cache)
            log("快照沿用本地（%.0f 小时前，%d 只）：fcap 由流通股本底表推算，"
                "spot 仅作 name 表与兜底，本次不请求 clist" % (age_h, len(df)))
            return df
        log("本地快照已 %.0f 小时，尝试刷新（或显式 --refresh-spot）" % age_h)
    try:
        raw = ak.stock_zh_a_spot_em()
    except Exception as e:
        # 兜底：抓不到时复用本地，避免整条流水线因一个非关键依赖而崩溃
        if cache.exists():
            df = pd.read_parquet(cache)
            log("快照抓取失败（%s），复用本地 spot.parquet（%d 只）"
                % (type(e).__name__, len(df)))
            return df
        raise
    df = raw
    df = df.rename(columns={"代码": "code", "名称": "name", "最新价": "price",
                            "涨跌幅": "chg", "成交额": "amount", "换手率": "turn",
                            "总市值": "tcap", "流通市值": "fcap"})
    df["code"] = df["code"].astype(str).str.zfill(6)
    df = df[["code", "name", "price", "chg", "amount", "turn", "tcap", "fcap"]]
    for c in ["price", "chg", "amount", "turn", "tcap", "fcap"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df.to_parquet(DATA / "spot.parquet", index=False)
    log("全市场快照落盘：%d 只" % len(df))
    return df


# ---------------------------------------------------------------- 个股日线
def _secid(code):
    return ("1." if code[0] in "56" else "0.") + code


def _fetch_bars_one(code, retry=2, end_date=None):
    """东财 push2his 单票日线，只留给 analysis/ 下的手动补数脚本；日更走 bar_sources。

    end_date=YYYYMMDD：K 线截止到两融最新基准日。

    不设 end 时，盘中运行会拿到「当日未完成 K 线」（close 是实时价），
    会让 build_data 的 close_last 变成盘中价、fcap 推算全错。
    """
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    p = {"secid": _secid(code), "fields1": "f1,f2,f3,f4,f5,f6",
         "fields2": "f51,f52,f53,f54,f55,f56,f57",
         "klt": "101", "fqt": "1", "end": end_date or "20500101",
         "lmt": str(BAR_LIMIT)}
    for a in range(retry + 1):
        try:
            r = requests.get(url, params=p, timeout=8, headers=UA)
            j = r.json()
            if not j.get("data") or not j["data"].get("klines"):
                return None
            recs = []
            for k in j["data"]["klines"]:
                f = k.split(",")
                recs.append((code, f[0], float(f[1]), float(f[2]), float(f[3]),
                             float(f[4]), float(f[5]), float(f[6])))
            return recs
        except Exception:
            time.sleep(0.3 * (a + 1))
    return None


def fetch_bars(codes, refresh=False, end_date=None):
    """抓日线并原子落盘。

    2026-11-12 事故修复：旧实现在 refresh 时先 unlink bars.parquet 再全量重抓，
    限流下只成功 3193/4198 只，直接丢掉 1005 只历史且不可逆。
    现在改为：旧表全程保留 → 写临时文件 → 覆盖率闸门 → os.replace 原子替换；
    闸门未通过时旧表为权威，只把新抓到的缺失行补入，历史永不丢。
    """
    cache = DATA / "bars.parquet"
    old = pd.read_parquet(cache) if cache.exists() else pd.DataFrame()
    have = set(old["code"].unique()) if len(old) else set()
    # refresh 时全量重抓，但不删旧表；非 refresh 只补缺失的票
    todo = sorted(set(codes)) if refresh else [c for c in codes if c not in have]
    log("日线：需要 %d 只，已缓存 %d，待抓 %d（refresh=%s end=%s）"
        % (len(codes), len(have), len(todo), refresh, end_date or "20500101"))

    target = ("%s-%s-%s" % (end_date[:4], end_date[4:6], end_date[6:8])) if end_date else None
    cols = ["code", "date", "open", "close", "high", "low", "volume", "amount"]
    new = pd.DataFrame(columns=cols)
    if todo and target:
        import bar_sources
        new, mix = bar_sources.collect(todo, old, target, BAR_LIMIT, bar_sources.md_home())
        log("  日线来源：MarketData %d，腾讯 %d，新浪 %d，未取到 %d"
            % (mix["marketdata"], mix["tx"], mix["sina"], mix["missing"]))
    elif todo:
        log("  没有截止日，无法取日线")
    if target:
        new = new[new["date"] <= target]
        old = old[old["date"] <= target]

    # 覆盖率闸门：仅在全量重抓(refresh)时启用。
    # 增量补票本来就只是补缺，拿「1 只 vs 全市场」做覆盖率比较没有意义。
    ok = True
    if refresh and len(old) and target:
        prev = sorted(old["date"].unique())[-1]
        cov_old = old[old["date"] == prev]["code"].nunique()
        cand = pd.concat([old, new], ignore_index=True) \
                 .drop_duplicates(subset=["code", "date"], keep="last")
        cov_new = cand[cand["date"] == target]["code"].nunique()
        ok = bool(cov_new >= 0.98 * cov_old) and not (todo and len(new) == 0)
        log("  覆盖率闸门：%s 覆盖 %d 只 / 旧表最新日 %s 覆盖 %d 只（阈值 98%%）→ %s"
            % (target, cov_new, prev, cov_old, "通过" if ok else "未通过"))
        if not ok:
            log("  未通过：保留旧表为权威，仅补入新抓到的缺失行，不覆盖历史")

    # 通过：新数据权威（可刷新同日价格）；未通过：旧数据权威（只补缺，不覆盖）
    parts = [old, new] if ok else [new, old]
    out = pd.concat(parts, ignore_index=True) \
            .drop_duplicates(subset=["code", "date"], keep="last")
    out = out.sort_values(["code", "date"])
    tmp = cache.with_name("bars.parquet.tmp")
    out.to_parquet(tmp, index=False)
    os.replace(tmp, cache)
    log("日线落盘：%d 行，%d 只（原子替换，闸门%s）"
        % (len(out), out["code"].nunique(), "通过" if ok else "未通过"))
    return out


# ---------------------------------------------------------------- 两融账户
def fetch_account():
    import akshare as ak
    df = ak.stock_margin_account_info()
    df = df.rename(columns={"日期": "date", "融资余额": "rz", "融券余额": "rq",
                            "融资买入额": "rz_buy", "融券卖出额": "rq_sell",
                            "担保物总价值": "collateral",
                            "平均维持担保比例": "ratio",
                            "有融资融券负债的投资者数量": "n_investor"})
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df.to_parquet(DATA / "account.parquet", index=False)
    log("两融账户统计落盘：%d 行，最新 %s，平均维持担保比例 %s%%"
        % (len(df), df["date"].iloc[-1],
           df["ratio"].dropna().iloc[-1] if df["ratio"].notna().any() else "NA"))
    return df


def main():
    t0 = time.time()
    refresh = "--refresh-bars" in sys.argv
    dates = get_trade_dates()
    log("交易日历：%s ~ %s（%d 个）" % (dates[0], dates[-1], len(dates)))

    margin = fetch_margin(dates)
    spot = fetch_spot(force="--refresh-spot" in sys.argv)
    codes = sorted(set(margin["code"].unique()))
    # K 线只取到两融最新基准日（T-1），杜绝 T 日盘中未完成 K 线混入
    end_date = str(margin["date"].max()).replace("-", "")[:8]
    log("日线截止日 end=%s（两融最新基准日）" % end_date)
    bars = fetch_bars(codes, refresh=refresh, end_date=end_date)
    acct = fetch_account()

    meta = {
        "as_of": dates[-1],
        "trade_dates": dates,
        "n_stock_margin": int(margin["code"].nunique()),
        "n_bars_code": int(bars["code"].nunique()),
        "n_spot": int(len(spot)),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 1),
    }
    (DATA / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    log("完成，用时 %.0fs" % (time.time() - t0))
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
