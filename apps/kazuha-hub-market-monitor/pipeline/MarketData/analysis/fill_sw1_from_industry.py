# -*- coding: utf-8 -*-
"""从 panorama/data/industry.json（stock-server sw_2021 时点分类）生成 sw1 补丁。

为什么用这个源
--------------
meta.json 的 sw1 是申万一级。可用的三个源里：
  - meta_source.json（akshare index_component_sw，2026-11-08 缓存）：口径对，但只覆盖
    当时 5,221 只，新上市的全没有；
  - catalog.json 的 industry：是证监会门类（「J 金融业」），**混进来会直接破坏行业中性化**，
    按 fill_meta.py 的 min-rate 逻辑必须拒绝；
  - panorama/data/industry.json：stock-server query_industry_data(as_of, taxonomy=sw)，
    申万 2021 时点分类 5,884 条。与 meta 既有 3,315 只实测一致率 99.97%（1 例冲突：
    688002 睿创微纳 本地=电子 / 外部=国防军工，按规矩只报不改）。

所以这是唯一既有口径保证、又能覆盖次新股的源。

已知局限
--------
  - industry.json 是「当前时点」快照，不是历史沿革。拿它填 meta 的静态 sw1，对早年回测
    存在行业前视（stock 被重新归类的情况）。这个局限 meta 里既有的 3,316 只本来就有，
    本次不新增该类风险，但要在报告里写明。
  - 长期退市股不在当前分类里（77 只），只能留空。

用法
----
  /opt/daily-tasks/venv/bin/python3 analysis/fill_sw1_from_industry.py --dry-run
  /opt/daily-tasks/venv/bin/python3 analysis/fill_sw1_from_industry.py --write
  写完接 apply_meta_patch.py 落库（记得先 mdlock_acquire）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
META = os.path.join(ROOT, "meta.json")
PATCH = os.path.join(ROOT, "meta_patch.json")
IND = "/opt/daily-tasks/workspace/panorama/data/industry.json"
OUT = os.path.join(HERE, "out")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="合并进 meta_patch.json")
    a = ap.parse_args(argv)

    meta = json.load(open(META, encoding="utf-8"))["stocks"]
    ind_rows = json.load(open(IND, encoding="utf-8"))
    ind = {}
    for x in ind_rows:
        if x.get("industry_name"):
            ind.setdefault(x["symbol"], x["industry_name"])
    print(f"industry.json：{len(ind_rows)} 条 / 唯一代码 {len(ind)}"
          f" ｜ 口径 {dict(Counter(x.get('taxonomy_version') for x in ind_rows))}")

    # ---- 1. 口径校验 ----
    same = diff = 0
    conf = []
    for c, v in meta.items():
        if not v.get("sw1") or c not in ind:
            continue
        if str(v["sw1"]).strip() == ind[c]:
            same += 1
        else:
            diff += 1
            conf.append((c, v.get("name"), v["sw1"], ind[c]))
    tot = same + diff
    rate = same / max(tot, 1)
    print(f"口径校验：一致 {same}/{tot} = {rate:.2%}（阈值 95%）")
    for x in conf[:12]:
        print(f"  ! 冲突 {x[0]} {x[1]} 本地={x[2]} 外部={x[3]}（不覆盖）")
    if rate < 0.95:
        print("✗ 口径一致率不足，拒绝生成补丁。", file=sys.stderr)
        return 2

    # ---- 2. 生成 sw1 补丁（只补空）----
    patch: dict[str, dict] = {}
    left = []
    for c, v in sorted(meta.items()):
        if v.get("sw1"):
            continue
        if c in ind:
            patch.setdefault(c, {})["sw1"] = ind[c]
        else:
            left.append((c, v.get("name"), (v.get("last") or "")[:7]))

    n = len(meta)
    before = sum(1 for v in meta.values() if v.get("sw1"))
    after = before + len(patch)
    print(f"\n待补 sw1：{len(patch)} 只 ｜ 无覆盖 {len(left)} 只")
    print(f"覆盖率：{before}/{n}={before/n:.1%} → {after}/{n}={after/n:.1%}")
    live_left = [x for x in left if x[2] >= "2026-11"]
    print(f"剩下的 {len(left)} 只里仍存续的 {len(live_left)} 只 {live_left[:8]}")
    print(f"行业分布（补的部分）：{dict(Counter(ind[c] for c in patch).most_common(8))}")

    os.makedirs(OUT, exist_ok=True)
    json.dump({"consistency": {"same": same, "diff": diff, "rate": round(rate, 4),
                               "conflicts": conf},
               "filled_sw1": len(patch), "left": left,
               "coverage": {"before": before, "after": after, "n": n}},
              open(os.path.join(OUT, "fill_sw1_report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    if not a.write:
        print("\n--dry-run：未写补丁。")
        return 0

    # 与已有补丁合并（list_date/board 那批已在库里，合并后重放是幂等的）
    old = {}
    if os.path.exists(PATCH):
        old = json.load(open(PATCH, encoding="utf-8"))
        if old:
            shutil.copy2(PATCH, PATCH + ".bak-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S"))
    for c, add in patch.items():
        old.setdefault(c, {}).update(add)
    json.dump(old, open(PATCH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n✓ 补丁已合并 {PATCH}（{len(old)} 只）→ 下一步 apply_meta_patch.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
