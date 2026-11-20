"""节流版全市场快照抓取 —— 规避东财翻页限流。

背景：akshare.stock_zh_a_spot_em() 用 0.5-1.5s 随机延迟翻 59 页，
连发过快会被 82.push2 节点在第 2 页起直接断连（RemoteDisconnected）。
本脚本改为 2.2s 匀速 + 单页 4 次退避重试，成功率高得多。

用法：
  python3 analysis/fetch_spot_throttled.py            # 抓取并写 data/spot.parquet
  python3 analysis/fetch_spot_throttled.py --dry-run  # 只抓不写
"""
import json
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

HOSTS = [
    "https://82.push2.eastmoney.com/api/qt/clist/get",
    "https://push2.eastmoney.com/api/qt/clist/get",
    "https://1.push2.eastmoney.com/api/qt/clist/get",
]
BASE = {
    "pn": "1", "pz": "100", "po": "1", "np": "1",
    "ut": "bd1d9ddb04089700cf9c27f6f7426281",
    "fltt": "2", "invt": "2", "fid": "f12",
    "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
    "fields": ("f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,"
               "f20,f21,f23,f24,f25,f22,f11,f62,f128,f136,f115,f152"),
}
GAP = 2.2          # 页间隔（秒）
PAGE_RETRY = 4     # 单页重试次数
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def get_page(pn, host_idx=0):
    """取一页，失败换节点 + 退避重试。"""
    last = None
    for a in range(PAGE_RETRY):
        host = HOSTS[(host_idx + a) % len(HOSTS)]
        p = dict(BASE)
        p["pn"] = str(pn)
        try:
            r = requests.get(host, params=p, timeout=20,
                             headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"})
            j = r.json()
            d = j.get("data")
            if d and d.get("diff"):
                return d
            last = "empty data"
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, str(e)[:80])
        time.sleep(1.5 * (a + 1))
    raise RuntimeError("page %d failed after %d tries, last=%s" % (pn, PAGE_RETRY, last))


def main():
    dry = "--dry-run" in sys.argv
    t0 = time.time()

    first = get_page(1, 0)
    total = int(first["total"])
    per = len(first["diff"])
    pages = -(-total // per)
    log("total=%d per_page=%d pages=%d" % (total, per, pages))

    rows = list(first["diff"])
    for pn in range(2, pages + 1):
        time.sleep(GAP)
        d = get_page(pn, pn % len(HOSTS))
        rows.extend(d["diff"])
        if pn % 10 == 0 or pn == pages:
            log("  %d/%d  rows=%d" % (pn, pages, len(rows)))

    df = pd.DataFrame(rows)
    log("抓取完成 %d 行，用时 %.0fs" % (len(df), time.time() - t0))

    rename = {"代码": "code", "名称": "name", "最新价": "price", "涨跌幅": "chg",
              "成交额": "amount", "换手率": "turn", "总市值": "tcap", "流通市值": "fcap"}
    df = df.rename(columns=rename)
    miss = [v for v in rename.values() if v not in df.columns]
    if miss:
        raise SystemExit("缺列 %s，实际列: %s" % (miss, list(df.columns)[:40]))

    df["code"] = df["code"].astype(str).str.zfill(6)
    df = df[["code", "name", "price", "chg", "amount", "turn", "tcap", "fcap"]]
    for c in ["price", "chg", "amount", "turn", "tcap", "fcap"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.drop_duplicates(subset=["code"], keep="last")

    # 与旧快照对比，确认是新数据
    old = None
    f = DATA / "spot.parquet"
    if f.exists():
        old = pd.read_parquet(f)
        log("旧快照 %d 行，价格变动>1%% 的标的占比 %.0f%%"
            % (len(old), 100 * (old.set_index("code")["price"]
                                .reindex(df["code"]).sub(df.set_index("code")["price"])
                                .abs().gt(old.set_index("code")["price"].reindex(df["code"]).abs() * 0.01)
                                ).mean()))

    log("有效 %d 行，fcap>0 的 %d 只" % (len(df), int((df["fcap"] > 0).sum())))
    if dry or (old is not None and len(df) < len(old) * 0.9):
        log("dry-run 或行数异常（<旧快照90%%），不写入")
        return

    if f.exists():
        bak = DATA / "spot.parquet.bak"
        bak.write_bytes(f.read_bytes())
        log("已备份旧快照 -> spot.parquet.bak")
    df.to_parquet(f, index=False)
    log("写入 data/spot.parquet：%d 行" % len(df))


if __name__ == "__main__":
    main()
