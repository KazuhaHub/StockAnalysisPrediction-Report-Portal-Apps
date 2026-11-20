# -*- coding: utf-8 -*-
"""盘点本地行情库相对「外部全市场」的缺口，分成可执行的补票批次。

为什么需要
----------
本地库只含**今天仍存续**的 2,036 只。用它回溯 2018 年起的规则，会同时踩两个坑：
  1. 成分前视：2021 年才 IPO 的票挤进 2018 年的横截面（`qdata.filter_listing_age`
     已能近似剔除）；
  2. 幸存者偏差：2014-06 之后退市/暂停上市的票一只都不在库里，而这部分
     `filter_listing_age` 修不掉——它们不是"还没上市"，是"已经不在人世"。

本脚本只做清单与分批，不写 bars。补票由 market_data.add() 完成。

批次划分（决策相关优先）
------------------------
  A 现存缺口 · list_date <= 2015-01-01
      → 对 start=2018 + 上市满 3 年这个口径**直接有效**，优先补。
  B 现存缺口 · 2015-01-01 < list_date
      → 当年不存在的票，默认口径下会被过滤掉；只影响将来把 start 后移，暂缓。
  C 退市/暂停上市 · 终止日 >= 2014-06-03
      → 修幸存者偏差，必须补，否则"活下来的票更好"会直接美化所有结论。
  D 退市/暂停上市 · 终止日 < 2014-06-03
      → 本地库起点之前就没了，无可用区间，跳过。

数据源全是 akshare 批量接口，不逐票请求；结果缓存到 pool_source.json，
"--offline" 可复用上次清单（断网/复现时用）。

用法
----
  /opt/daily-tasks/venv/bin/python3 expand_pool.py
  /opt/daily-tasks/venv/bin/python3 expand_pool.py --offline
  /opt/daily-tasks/venv/bin/python3 expand_pool.py --batch A --write-codes A.txt
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import warnings

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
META = os.path.join(HERE, "meta.json")
CACHE = os.path.join(HERE, "pool_source.json")
GAP = os.path.join(HERE, "pool_gap.json")

LIB_START = "2014-06-03"       # 本地库最早一根日线
DECISION_CUTOFF = "2015-01-01"  # start=2018 + 上市满 3 年


def _six(x) -> str:
    s = re.sub(r"\D", "", str(x))
    return s.zfill(6)[-6:]


def _date(x) -> str | None:
    s = str(x)[:10].replace("/", "-")
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    return s if m else None


def fetch() -> dict:
    import akshare as ak

    listed: dict[str, dict] = {}
    sources = []

    def add(code, name, d, tag, status, delist=None):
        c = _six(code)
        dd = _date(d)
        # B 股（深 200xxx / 沪 900xxx）不进 A 股池。交易所的退市名单里混着它们，
        # 补进来只会得到「无法识别交易所」——不是数据源故障，是口径不该包含。
        if not c or c.startswith(("200", "900")) or c in listed:
            return 0
        listed[c] = {"name": str(name).strip(), "list_date": dd,
                     "status": status, "delist_date": delist, "source": tag}
        return 1

    # ---- 现存
    d = ak.stock_info_sz_name_code(symbol="A股列表")
    n = sum(add(r["A股代码"], r["A股简称"], r["A股上市日期"],
                "stock_info_sz_name_code(A股列表)", "alive") for _, r in d.iterrows())
    sources.append({"source": "sz 现存", "rows": len(d), "new": n})
    for sym in ("主板A股", "科创板"):
        d = ak.stock_info_sh_name_code(symbol=sym)
        n = sum(add(r["证券代码"], r["证券简称"], r["上市日期"],
                    f"stock_info_sh_name_code({sym})", "alive") for _, r in d.iterrows())
        sources.append({"source": f"sh 现存 {sym}", "rows": len(d), "new": n})

    # ---- 退市 / 暂停上市
    d = ak.stock_info_sh_delist()
    n = sum(add(r["公司代码"], r["公司简称"], r["上市日期"],
                "stock_info_sh_delist", "delisted", _date(r["暂停上市日期"]))
            for _, r in d.iterrows())
    sources.append({"source": "sh 退市", "rows": len(d), "new": n})
    d = ak.stock_info_sz_delist()
    n = sum(add(r["证券代码"], r["证券简称"], r["上市日期"],
                "stock_info_sz_delist", "delisted", _date(r["终止上市日期"]))
            for _, r in d.iterrows())
    sources.append({"source": "sz 退市", "rows": len(d), "new": n})

    return {"fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
            "listed": listed, "sources": sources}


def load(offline: bool) -> dict:
    if offline:
        if not os.path.exists(CACHE):
            raise SystemExit(f"--offline 但缓存不存在：{CACHE}")
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    c = fetch()
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=1)
    return c


def split_batches(src: dict) -> dict:
    meta = json.load(open(META, encoding="utf-8"))["stocks"]
    have = set(meta)
    listed = src["listed"]

    A, B, C, D, unknown_date = [], [], [], [], []
    n_b = 0
    for code, v in listed.items():
        if code.startswith(("200", "900")):
            n_b += 1          # B 股：不进 A 股池（--offline 走缓存时也要挡一次）
            continue
        ld, st, dd = v.get("list_date"), v["status"], v.get("delist_date")
        if st == "delisted":
            if dd and dd < LIB_START:
                D.append(code)            # 库起点前就没了
            elif dd:
                C.append(code)            # 区间内退市，有可用历史
            else:
                unknown_date.append(code)  # 退市日缺失，先按可补处理
                C.append(code)
        else:
            if code in have:
                continue
            if ld is None:
                unknown_date.append(code)
                B.append(code)            # 上市日未知，保守放 B
            elif ld <= DECISION_CUTOFF:
                A.append(code)
            else:
                B.append(code)

    for lst in (A, B, C, D):
        lst.sort()

    def info(codes):
        return [{"code": c, "name": listed[c]["name"],
                 "list_date": listed[c].get("list_date"),
                 "delist_date": listed[c].get("delist_date"),
                 "status": listed[c]["status"]} for c in codes]

    return {
        "as_of": dt.datetime.now().isoformat(timespec="seconds"),
        "lib_start": LIB_START,
        "decision_cutoff": DECISION_CUTOFF,
        "n_local": len(meta),
        "n_external": len(listed) - n_b,
        "n_b_share_excluded": n_b,
        "batches": {
            "A_现存缺口_上市早于2015": info(A),
            "B_现存缺口_2015后上市": info(B),
            "C_退市_库区间内有历史": info(C),
            "D_退市_库起点前已退": info(D),
        },
        "counts": {"A": len(A), "B": len(B), "C": len(C), "D": len(D),
                   "unknown_list_date": len(unknown_date),
                   "A_plus_C": len(A) + len(C)},
        "sources": src["sources"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="用 pool_source.json 缓存")
    ap.add_argument("--batch", help="只导出某批代码，如 A / C / AC")
    ap.add_argument("--write-codes", help="把代码写入该文件（每行一个）")
    a = ap.parse_args()

    src = load(a.offline)
    print(f"外部名单  {len(src['listed'])} 只（{src['fetched_at']}）")
    for s in src["sources"]:
        print(f"  {s['source']:<34} 行 {s['rows']:>5}  新增 {s['new']:>5}")

    g = split_batches(src)
    with open(GAP, "w", encoding="utf-8") as f:
        json.dump(g, f, ensure_ascii=False, indent=1)

    print(f"\n本地库 {g['n_local']} 只 ｜ 外部 {g['n_external']} 只 ｜ "
          f"库起点 {g['lib_start']} ｜ 决策 cutoff {g['decision_cutoff']}")
    label = {"A": "A 现存缺口·上市早于2015（决策相关）",
             "B": "B 现存缺口·2015后上市（默认口径被过滤）",
             "C": "C 退市·库区间内有历史（修幸存者偏差）",
             "D": "D 退市·库起点前已退（跳过）"}
    for k, v in g["batches"].items():
        print(f"  {k:<24} {len(v):>5} 只   {label[k.split('_')[0]]}")
    print(f"  {'A+C 本轮应补':<24} {g['counts']['A_plus_C']:>5} 只")
    print(f"  {'上市日未知':<24} {g['counts']['unknown_list_date']:>5} 只")
    print(f"\n清单已写 {GAP}")

    if a.batch:
        keys = {"A": "A_现存缺口_上市早于2015", "B": "B_现存缺口_2015后上市",
                "C": "C_退市_库区间内有历史", "D": "D_退市_库起点前已退"}
        codes = []
        for ch in a.batch.upper():
            codes += [x["code"] for x in g["batches"][keys[ch]]]
        print(f"批次 {a.batch.upper()}：{len(codes)} 只")
        if a.write_codes:
            with open(a.write_codes, "w", encoding="utf-8") as f:
                f.write("\n".join(codes) + "\n")
            print(f"已写 {a.write_codes}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
