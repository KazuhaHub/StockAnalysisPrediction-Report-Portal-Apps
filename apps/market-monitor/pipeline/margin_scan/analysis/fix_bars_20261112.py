"""修复 2026-11-12 补跑造成的日线缺失。

背景：update.sh --refresh-bars 先删 bars.parquet 再全量重抓 4198 只，
在开盘高峰被东财限流，仅 3193 只成功，且末尾混入 11-12 盘中未完成 K 线。

修复：
  1. 以新数据为基底，剔除 11-12 盘中行；
  2. 从备份恢复完全缺失的 1005 只历史；
  3. 为所有缺 11-11 的票补抓当日 K 线（lmt=5，只取 11-11）。
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TARGET = "2026-11-11"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
WORKERS = 4


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def secid(code):
    return ("1." if code[0] in "56" else "0.") + code


def fetch_one(code, retry=5):
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    p = {"secid": secid(code), "fields1": "f1,f2,f3,f4,f5,f6",
         "fields2": "f51,f52,f53,f54,f55,f56,f57",
         "klt": "101", "fqt": "1", "end": "20500101", "lmt": "4"}
    for a in range(retry):
        try:
            r = requests.get(url, params=p, timeout=8, headers={"User-Agent": UA})
            j = r.json()
            ks = (j.get("data") or {}).get("klines") or []
            for k in ks:
                f = k.split(",")
                if f[0] == TARGET:
                    return (code, f[0], float(f[1]), float(f[2]), float(f[3]),
                            float(f[4]), float(f[5]), float(f[6]))
            return None          # 该票 11-11 无 K 线（停牌/退市）
        except Exception:
            time.sleep(0.4 * (a + 1))
    return "FAIL"


def main():
    backup = pd.read_parquet(ROOT / "backup_20261112" / "bars.parquet")
    new = pd.read_parquet(DATA / "bars.parquet")
    log("备份 %d 只(到%s) / 新版 %d 只(到%s)"
        % (backup.code.nunique(), backup.date.max(),
           new.code.nunique(), new.date.max()))

    base = new[new["date"] != "2026-11-12"].copy()
    have11 = set(base[base["date"] == TARGET]["code"])

    missing_all = sorted(set(backup["code"]) - set(new["code"]))
    restore = backup[backup["code"].isin(missing_all)]
    log("完全缺失 %d 只，从备份恢复 %d 行" % (len(missing_all), len(restore)))

    # 需要补 TARGET 的票：完全缺失的 + 存在但 TARGET 缺的
    todo = sorted((set(backup["code"]) | set(base["code"])) - have11)
    log("待补 %s 行情：%d 只（已覆盖 %d 只）" % (TARGET, len(todo), len(have11)))

    recs, fails = [], []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch_one, c): c for c in todo}
        done = 0
        for f in as_completed(futs):
            r = f.result()
            done += 1
            if r == "FAIL":
                fails.append(futs[f])
            elif r:
                recs.append(r)
            if done % 200 == 0 or done == len(todo):
                log("  进度 %d/%d  命中=%d 失败=%d  用时%.0fs"
                    % (done, len(todo), len(recs), len(fails), time.time() - t0))

    cols = ["code", "date", "open", "close", "high", "low", "volume", "amount"]
    add = pd.DataFrame(recs, columns=cols) if recs else pd.DataFrame(columns=cols)
    log("补抓命中 %d 只，彻底失败 %d 只" % (len(add), len(fails)))

    out = pd.concat([base, restore, add], ignore_index=True)
    out = out.drop_duplicates(subset=["code", "date"], keep="last")
    out = out.sort_values(["code", "date"])
    out.to_parquet(DATA / "bars.parquet", index=False)

    log("落盘：%d 行，%d 只，日期 %s ~ %s"
        % (len(out), out.code.nunique(), out.date.min(), out.date.max()))
    cov = out[out["date"] == TARGET]["code"].nunique()
    log("校验 %s 覆盖：%d 只（备份 11-10 覆盖 %d 只）"
        % (TARGET, cov, backup[backup["date"] == backup["date"].max()]["code"].nunique()))
    if fails:
        log("仍未取到（可能停牌/退市）：%s" % ",".join(fails[:20]))


if __name__ == "__main__":
    main()
