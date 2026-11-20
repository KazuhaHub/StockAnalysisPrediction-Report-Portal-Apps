# -*- coding: utf-8 -*-
"""从 catalog.json 生成 list_date / board 补丁，交给 apply_meta_patch.py 落库。

为什么不直接用 fill_meta.py
----------------------------
fill_meta.py 走 akshare 的「当前上市名录」，对退市股无效；而本次缺 list_date 的
217 只里有 84 只已退市。catalog.json（instruments API 全量名录 10,666 只）自带
listed_date 与 delisted_date，退市股也覆盖，实测对这 217 只 100% 有值，
且与 meta 既有 5,616 只的 list_date 口径一致率 99.95%（3 例冲突均为退市股，只报不改）。

口法
----
只产出补丁，不改 meta.json、不碰 bars/*.parquet。板块按代码前缀机械推断，
与 fill_meta.py 的 BOARD_PREFIX 同源，避免引入第三套板块口径。

用法
----
  /opt/daily-tasks/venv/bin/python3 analysis/fill_list_date_from_catalog.py --dry-run
  /opt/daily-tasks/venv/bin/python3 analysis/fill_list_date_from_catalog.py --write
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
META = os.path.join(ROOT, "meta.json")
CAT = os.path.join(ROOT, "catalog.json")
PATCH = os.path.join(ROOT, "meta_patch.json")
OUT = os.path.join(HERE, "out")

# 与 fill_meta.py / qstab.board_of 完全一致
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


def d10(x) -> str | None:
    if not x:
        return None
    s = str(x).strip().replace("/", "-")
    return s[:10] if len(s) >= 10 else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="写出 meta_patch.json")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不写文件（默认行为）")
    a = ap.parse_args(argv)

    meta = json.load(open(META, encoding="utf-8"))["stocks"]
    cat = {x["symbol"]: x for x in json.load(open(CAT, encoding="utf-8"))
           if x.get("type") == "STOCK"}

    # ---- 1. 口径校验：用既有标注当标准答案 ----
    same = diff = 0
    conflicts = []
    for c, v in meta.items():
        ld = d10(v.get("list_date"))
        x = cat.get(c)
        if not ld or not x or not x.get("listed_date"):
            continue
        ext = d10(x["listed_date"])
        if ld == ext:
            same += 1
        else:
            diff += 1
            conflicts.append((c, v.get("name"), ld, ext, bool(x.get("delisted_date"))))
    tot = same + diff
    rate = same / max(tot, 1)
    print(f"口径校验：catalog listed_date 与 meta 一致 {same}/{tot} = {rate:.2%}"
          f"（阈值 95%）")
    for c in conflicts:
        print(f"  ! 冲突 {c[0]} {c[1]} 本地={c[2]} 外部={c[3]} 退市={c[4]}（不覆盖）")
    if rate < 0.95:
        print("✗ 口径一致率不足，拒绝生成补丁。", file=sys.stderr)
        return 2

    # ---- 2. 生成补丁（只补空，不覆盖）----
    patch: dict[str, dict] = {}
    stat = Counter()
    no_cat, bad_order = [], []
    for c, v in sorted(meta.items()):
        add: dict[str, str] = {}
        if not v.get("list_date"):
            x = cat.get(c)
            ld = d10(x.get("listed_date")) if x else None
            if ld:
                add["list_date"] = ld
                stat["list_date"] += 1
                if x.get("delisted_date"):
                    stat["list_date_delisted"] += 1
            else:
                no_cat.append((c, v.get("name")))
        if not v.get("board"):
            b = board_of(c)
            if b:
                add["board"] = b
                stat["board"] += 1
        if add:
            patch[c] = add
            # list_date 不能晚于本库首根 K 线（首根 K 线一定不早于上市日）
            f = d10(v.get("first"))
            if add.get("list_date") and f and add["list_date"] > f:
                bad_order.append((c, v.get("name"), add["list_date"], f))

    print(f"\n待补：list_date {stat['list_date']} 只（其中退市 {stat['list_date_delisted']}）"
          f" ｜ board {stat['board']} 只 ｜ 涉及 {len(patch)} 只")
    print(f"catalog 无上市日：{len(no_cat)} 只 {no_cat[:10]}")
    print(f"上市日晚于首根 K 线：{len(bad_order)} 只 {bad_order[:10]}")

    # ---- 3. 覆盖率预估 ----
    n = len(meta)
    after_ld = sum(1 for v in meta.values() if v.get("list_date")) + stat["list_date"]
    after_bd = sum(1 for v in meta.values() if v.get("board")) + stat["board"]
    print(f"覆盖率预估：list_date {after_ld}/{n}={after_ld/n:.1%} ｜ board {after_bd}/{n}={after_bd/n:.1%}")

    if bad_order:
        print("✗ 存在上市日晚于首根 K 线的矛盾记录，拒绝写补丁。", file=sys.stderr)
        return 4

    os.makedirs(OUT, exist_ok=True)
    rep = {"consistency": {"same": same, "diff": diff, "rate": round(rate, 4),
                           "conflicts": conflicts},
           "filled": dict(stat), "no_catalog": no_cat,
           "coverage_after": {"list_date": after_ld, "board": after_bd, "n": n}}
    json.dump(rep, open(os.path.join(OUT, "fill_list_date_report.json"), "w",
                        encoding="utf-8"), ensure_ascii=False, indent=1)

    if not a.write:
        print("\n--dry-run：未写补丁。")
        return 0

    if os.path.exists(PATCH):
        shutil.copy2(PATCH, PATCH + ".bak-" + __import__("datetime").datetime.now().strftime("%Y%m%d-%H%M%S"))
    json.dump(patch, open(PATCH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n✓ 补丁已写 {PATCH}（{len(patch)} 只）→ 下一步跑 apply_meta_patch.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
