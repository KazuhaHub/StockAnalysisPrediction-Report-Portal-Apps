#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成流通股本底表 data/float_shares.parquet。

为什么需要它
------------
build_data.py 原式 fcap_T = fcap_spot × close_T / close_last，而 close_last 就是
bars 最后一天(=T)，close_T == close_last ⇒ scale 恒为 1，fcap_T 恒等于 fcap_spot。
也就是说每天抓 59 页快照，只为了拿一个几乎不变的静态量，一旦快照抓不到，
整个流水线就断（2026-11-12 事故）。

fcap = 流通股本 × 收盘价。流通股本是慢变量，建一次底表后每日由日线算出即可：

    fcap_T = fcap_base × close_T / close_base

用「比值」而非 float_shares × close_T，可对抗复权基准整体缩放（fqt 变更、
源端因子调整）——只要 close_T 与 close_base 来自同一份 bars 就成立。

base_date 的确定（不靠人工指定）
--------------------------------
spot.parquet 是 09:01 盘前抓的，price 全为 NaN，fcap 对应的是「上一交易日收盘」。
脚本遍历 bars 最近若干个交易日，用「反推股本 / gdhs 总股本」的吻合度自动择优，
选出与快照 fcap 口径最自洽的那一天。

用法：python3 analysis/build_float_shares.py
输出：data/float_shares.parquet + data/float_shares.meta.json
"""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def main():
    spot = pd.read_parquet(DATA / "spot.parquet")
    spot["code"] = spot["code"].astype(str).str.zfill(6)
    spot = spot.drop_duplicates(subset=["code"], keep="last").set_index("code")
    spot = spot[spot["fcap"] > 0]
    log("快照有效 fcap：%d 只" % len(spot))

    bars = pd.read_parquet(DATA / "bars.parquet")
    close_w = bars.pivot(index="date", columns="code", values="close")
    recent = sorted(close_w.index)[-6:]
    log("候选 base_date：%s" % ", ".join(recent))

    # 交叉校验参照：gdhs 的总股本（akshare 股东户数表，2026-11-12 抓取）
    gdhs = pd.read_parquet(DATA / "gdhs.parquet")
    gcol = "总股本"
    g = gdhs[["代码", gcol]].dropna().copy()
    g["code"] = g["代码"].astype(str).str.zfill(6)
    total_shares = g.drop_duplicates(subset=["code"], keep="last").set_index("code")[gcol]
    total_shares = pd.to_numeric(total_shares, errors="coerce")
    total_shares = total_shares[total_shares > 0]

    best = None
    for d in recent:
        c = close_w.loc[d]
        fs = (spot["fcap"] / c.reindex(spot.index)).replace([np.inf, -np.inf], np.nan)
        fs = fs[(fs > 1e6) & (fs < 1e12)].dropna()
        common = fs.index.intersection(total_shares.index)
        ratio = (fs.reindex(common) / total_shares.reindex(common)).dropna()
        ratio = ratio[(ratio > 0.01) & (ratio < 10)]
        hit = float((ratio <= 1.05).mean()) if len(ratio) else 0.0
        med = float(ratio.median()) if len(ratio) else np.nan
        score = hit - abs(med - 1.0) * 0.5
        log("  %s  可反推 %4d 只 | 校验 %4d 只 | 比值中位 %.4f | <=1.05 占比 %.2f%% | score %.4f"
            % (d, len(fs), len(ratio), med, hit * 100, score))
        if best is None or score > best["score"]:
            best = {"date": d, "score": score, "fs": fs, "hit": hit, "med": med,
                    "n_check": len(ratio)}

    d = best["date"]
    log("选定 base_date = %s（校验 %d 只，比值中位 %.4f，<=1.05 占比 %.2f%%）"
        % (d, best["n_check"], best["med"], best["hit"] * 100))
    if best["hit"] < 0.90:
        raise SystemExit("股本交叉校验吻合度不足 90%%，拒绝建表（base_date=%s）" % d)

    close_base = close_w.loc[d]
    fs = best["fs"].rename("float_shares").to_frame()
    fs["fcap_base"] = spot["fcap"].reindex(fs.index)
    fs["base_close"] = close_base.reindex(fs.index)
    fs["name"] = spot["name"].reindex(fs.index)
    fs["base_date"] = d
    fs = fs.reset_index()

    # 原子写，避免半截文件
    tmp = DATA / "float_shares.parquet.tmp"
    fs.to_parquet(tmp, index=False)
    tmp.replace(DATA / "float_shares.parquet")

    meta = {
        "base_date": d,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "data/spot.parquet (fcap, 盘前快照=上一交易日收盘) + data/bars.parquet (前复权 close)",
        "cross_check": "data/gdhs.parquet 总股本",
        "n": int(len(fs)),
        "n_cross_check": int(best["n_check"]),
        "ratio_median": round(best["med"], 4),
        "hit_le_105": round(best["hit"], 4),
        "formula": "fcap_T = fcap_base * close_T / close_base",
        "note": ("流通股本为慢变量，解禁/增发/送转密集期需低频重跑本脚本校准；"
                 "spot.parquet 每 7 天自动尝试刷新，新进入两融标的的新股入池最多滞后 7 天"
                 "（刷新失败时按原缓存降级，不阻断流水线）"),
    }
    (DATA / "float_shares.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    log("落盘 float_shares.parquet：%d 只；meta 已写" % len(fs))
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
