# -*- coding: utf-8 -*-
"""补齐 ~/MarketData/meta.json 里整行缺失的元数据（只填空，不覆盖既有值）。

背景
----
meta.json 里 2,036 只票中有 515 只 board/list_date/sw1/sw3/sw_l3_code 全为 None，
但它们的日线是齐的（其中 325 只从 2014-06 库起点就有数据，包括平安银行、
山东钢铁这类大票）。这不是「新股补不到」，而是当初从 factor_lab 的 ss_cache
迁移时这批票没带上元数据，后来通过别的渠道补了行情却没补元信息。

后果有两个，都不报错：
  1. qdata._load_marketdata 只认 sw1，这 515 只在行业中性化里被整体略过；
  2. 没有 list_date 就做不了「检验起点时是否已上市」的成分前视近似检验。

数据源（akshare，均一次批量取全市场，不做 515 次单票请求）
--------------------------------------------------------
  - 申万一级行业：sw_index_first_info() 拿 31 个行业代码 → index_component_sw()
    逐个取成分。与现有 1,521 只标注做过一致性校验，口径相同才回填。
  - 上市日期：stock_info_sz_name_code("A股列表")（深市）
    + stock_info_sh_name_code("主板A股"/"科创板")（沪市）。
  - board：按代码前缀机械推断，避免引入第三套口径。

原则：只填 None，绝不覆盖已有值；冲突写进报告不静默吞掉；
      原始映射缓存在 meta_source.json，断网也能复现上一次回填。
      全程不碰 bars/*.parquet。

用法（只能用 3.9 解释器，PATH 里的 3.13 没有 pandas）
----------------------------------------------------
  /opt/daily-tasks/venv/bin/python3 fill_meta.py            # 拉取并回填
  /opt/daily-tasks/venv/bin/python3 fill_meta.py --offline  # 用缓存回填
  /opt/daily-tasks/venv/bin/python3 fill_meta.py --check    # 只体检，不写
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys
import warnings
from collections import Counter

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
META = os.path.join(HERE, "meta.json")
CACHE = os.path.join(HERE, "meta_source.json")

# 与 qstab.board_of / market_data 的板块口径保持一致
BOARD_PREFIX = (
    ("沪主板", ("600", "601", "603", "605")),
    ("深主板", ("000", "001", "002", "003")),
    ("创业板", ("300", "301", "302")),
    ("科创板", ("688", "689")),
)


def board_of(code: str) -> str | None:
    for name, prefixes in BOARD_PREFIX:
        if code.startswith(prefixes):
            return name
    return None


def _six(x) -> str:
    return str(x).strip().zfill(6)


def _date(x) -> str | None:
    if x is None or str(x) in ("", "NaT", "None", "nan"):
        return None
    if hasattr(x, "strftime"):
        return x.strftime("%Y-%m-%d")
    s = str(x).strip().replace("/", "-")
    return s[:10] if len(s) >= 10 else None


def fetch() -> dict:
    """一次性拉全市场申万一级映射与上市日期，返回可复现的缓存结构。"""
    import akshare as ak

    ind: dict[str, str] = {}
    first = ak.sw_index_first_info()
    rows = []
    for _, r in first.iterrows():
        code = str(r["行业代码"]).split(".")[0]
        name = str(r["行业名称"]).strip()
        try:
            comp = ak.index_component_sw(symbol=code)
        except Exception as e:
            print(f"  ! 申万 {code} {name} 取成分失败：{type(e).__name__} {e}", file=sys.stderr)
            continue
        n = 0
        for c in comp["证券代码"]:
            ind[_six(c)] = name
            n += 1
        rows.append({"code": code, "name": name, "n": n})
    print(f"  申万一级：{len(rows)} 个行业，成分映射 {len(ind)} 只")

    listed: dict[str, str] = {}
    sources = []

    def add(df, date_col, code_col, tag):
        n = 0
        for _, r in df.iterrows():
            c, d = _six(r[code_col]), _date(r[date_col])
            if d and c not in listed:
                listed[c] = d
                n += 1
        sources.append({"source": tag, "rows": len(df), "new": n})

    d = ak.stock_info_sz_name_code(symbol="A股列表")
    add(d, "A股上市日期", "A股代码", "stock_info_sz_name_code(A股列表)")
    for sym in ("主板A股", "科创板"):
        d = ak.stock_info_sh_name_code(symbol=sym)
        add(d, "上市日期", "证券代码", f"stock_info_sh_name_code({sym})")
    print(f"  上市日期：{len(listed)} 只 " + " / ".join(
        f"{s['source'].split('(')[-1].rstrip(')')}={s['new']}" for s in sources))

    return {"fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
            "industry": ind, "listed": listed, "sw_rows": rows, "sources": sources}


def load_cache(offline: bool) -> dict:
    if offline:
        if not os.path.exists(CACHE):
            raise SystemExit(f"--offline 但缓存不存在：{CACHE}")
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    c = fetch()
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=1)
    return c


def consistency(meta_stocks: dict, cache: dict) -> dict:
    """拿已有标注当标准答案，验证外部口径能不能混用。"""
    ind, listed = cache["industry"], cache["listed"]
    same = diff = 0
    diff_samples = []
    for c, v in meta_stocks.items():
        if v.get("sw1") and c in ind:
            if str(v["sw1"]).strip() == ind[c]:
                same += 1
            else:
                diff += 1
                if len(diff_samples) < 8:
                    diff_samples.append(f"{c} 本地={v['sw1']} 外部={ind[c]}")
    ld_same = ld_diff = 0
    ld_samples = []
    for c, v in meta_stocks.items():
        if v.get("list_date") and c in listed:
            if str(v["list_date"])[:10] == listed[c]:
                ld_same += 1
            else:
                ld_diff += 1
                if len(ld_samples) < 5:
                    ld_samples.append(f"{c} 本地={v['list_date']} 外部={listed[c]}")
    return {"sw1": {"same": same, "diff": diff, "rate": same / max(same + diff, 1),
                    "samples": diff_samples},
            "list_date": {"same": ld_same, "diff": ld_diff,
                          "rate": ld_same / max(ld_same + ld_diff, 1),
                          "samples": ld_samples}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="用 meta_source.json 缓存回填，不联网")
    ap.add_argument("--check", action="store_true", help="只体检，不写 meta.json")
    ap.add_argument("--min-rate", type=float, default=0.95,
                    help="申万口径一致率低于此值则拒绝回填（默认 0.95）")
    a = ap.parse_args(argv)

    with open(META, encoding="utf-8") as f:
        meta = json.load(f)
    stocks = meta["stocks"]
    before = {c: dict(v) for c, v in stocks.items()}

    missing = [c for c, v in stocks.items() if not v.get("sw1")]
    print(f"meta.json：{len(stocks)} 只，整行缺元数据 {len(missing)} 只")

    cache = load_cache(a.offline)
    cons = consistency(stocks, cache)
    print(f"口径校验：申万 sw1 一致 {cons['sw1']['same']}/{cons['sw1']['same']+cons['sw1']['diff']}"
          f" = {cons['sw1']['rate']:.1%} ｜ 上市日期一致 {cons['list_date']['rate']:.1%}")
    for s in cons["sw1"]["samples"] + cons["list_date"]["samples"]:
        print(f"  ! 冲突 {s}")
    if cons["sw1"]["rate"] < a.min_rate:
        print(f"\n✗ 申万口径一致率 {cons['sw1']['rate']:.1%} < {a.min_rate:.0%}，拒绝回填。"
              "两套行业分类混用会直接破坏行业中性化。", file=sys.stderr)
        return 2

    ind, listed = cache["industry"], cache["listed"]
    filled = Counter()
    still = Counter()
    for c in missing:
        v = stocks[c]
        if not v.get("board"):
            b = board_of(c)
            if b:
                v["board"] = b
                filled["board"] += 1
        if not v.get("list_date") and c in listed:
            v["list_date"] = listed[c]
            filled["list_date"] += 1
        if not v.get("sw1") and c in ind:
            v["sw1"] = ind[c]
            filled["sw1"] += 1
        for f in ("board", "list_date", "sw1"):
            if not v.get(f):
                still[f] += 1
        v["meta_source"] = f"akshare@{cache['fetched_at'][:10]}"

    print(f"\n回填：board {filled['board']} ｜ list_date {filled['list_date']} ｜ sw1 {filled['sw1']}")
    print(f"仍缺：{dict(still) or '无'}")

    # 机器校验 1：既有值一个都不许变
    changed = [c for c in before
               if any(before[c].get(k) != stocks[c].get(k)
                      for k in ("name", "board", "list_date", "sw1", "sw3", "sw_l3_code",
                                "first", "last", "n_bars"))]
    # 只对「原本非空」的字段判变更；填空是预期内的
    bad = [c for c in changed
           if any(before[c].get(k) not in (None, "") and before[c].get(k) != stocks[c].get(k)
                  for k in ("board", "list_date", "sw1", "sw3", "sw_l3_code"))]
    print(f"机器校验：覆盖既有非空值 {len(bad)} 处（必须为 0）")
    if bad:
        print("  !", bad[:8], file=sys.stderr)
        return 3

    # 机器校验 2：回填后覆盖率
    cover = {f: sum(1 for v in stocks.values() if v.get(f))
             for f in ("board", "list_date", "sw1", "name")}
    print("覆盖率：" + " ｜ ".join(f"{f} {n}/{len(stocks)}={n/len(stocks):.1%}"
                                for f, n in cover.items()))
    # 机器校验 3：list_date 与 first 不能矛盾（上市日不可能晚于首根 K 线）
    bad_ld = [(c, v["list_date"], v["first"]) for c, v in stocks.items()
              if v.get("list_date") and v.get("first") and v["list_date"] > v["first"]]
    print(f"上市日期晚于首根 K 线：{len(bad_ld)} 只（必须为 0）")
    if bad_ld:
        print("  !", bad_ld[:5], file=sys.stderr)
        return 4

    if a.check:
        print("\n--check：未写回。")
        return 0

    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = f"{META}.bak-{ts}"
    shutil.copy2(META, bak)
    meta["meta_fill"] = {
        "at": cache["fetched_at"], "source": "akshare sw_index_first_info / index_component_sw "
        "+ stock_info_sz_name_code / stock_info_sh_name_code",
        "filled": dict(filled), "still_missing": dict(still),
        "consistency": {k: {"same": v["same"], "diff": v["diff"], "rate": round(v["rate"], 4)}
                        for k, v in cons.items()},
        "rule": "只填 None，不覆盖既有值；不触碰 bars/*.parquet",
    }
    tmp = META + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    os.replace(tmp, META)
    print(f"\n✓ 已写回 {META}\n  备份 {bak}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
