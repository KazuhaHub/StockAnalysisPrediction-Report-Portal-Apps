"""真实双池对照：稳定性判级能不能提前认出"换池会改口"的信号。

随机重抽样只能测样本量敏感性，测不出构成变化——它抽不到池子里本来没有的票。
2026-11-07 那次 1,492 → 1,988 的改口，起因是补进沪深 300/中证 500 里缺的大中盘，
属于构成变化。所以这里用真实的两个池做对照：

  池 A = 全池剔除第二批补入的 482 只 → 还原 1,492 只
  池 B = 全池 1,988 只

对每条信号，在两个池上各算主口径 Δ 与 t，看符号/显著性是否改口；
再对照 `qsr stab` 给出的 grade/scope，检验判级有没有预测力。

用独立进程跑，避免与全量 stab 抢 CPU。
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.expanduser("~/.workbuddy/skills/quant-signal-research/scripts"))

import qdata  # noqa: E402
import qstab  # noqa: E402


def main() -> int:
    reg = json.load(open(os.path.expanduser(
        "~/.workbuddy/skills/quant-signal-research/registry/signals.json"),
        encoding="utf-8"))["signals"]
    later = {c.strip() for c in open("/tmp/missing_lc.txt") if c.strip()}
    print(f"第二批补入名单 {len(later)} 只", flush=True)

    univ = qdata.load_universe(start="2018-01-01", verbose=False)
    # 键是 "000001.SZ" 这种格式，取前 6 位；不能用 [-6:]（那会得到 "001.SZ"）
    big = univ
    small = {c: d for c, d in univ.items() if c[:6] not in later}
    print(f"池 B（全池）{len(big)} 只 ｜ 池 A（剔除后）{len(small)} 只 "
          f"｜ 剔除 {len(big) - len(small)} 只", flush=True)
    if len(big) == len(small):
        print("✗ 剔除没有生效，检查代码格式", file=sys.stderr)
        return 2

    # 预先缓存可交易性，两个池共用，避免重复计算
    rows = []
    for s in reg:
        if s.get("status") == "retired" or s.get("events_file"):
            continue
        h = int(s.get("horizon", 5))
        tgt = s.get("target", "return")
        try:
            ra = qstab.delta_t(*_fg_of(s, small, h, tgt), h)
            rb = qstab.delta_t(*_fg_of(s, big, h, tgt), h)
        except Exception as e:      # 伪代码规则
            print(f"{s['id']} 跳过：{type(e).__name__}: {str(e)[:60]}", flush=True)
            continue
        st = s.get("stability") or {}
        rows.append({
            "id": s["id"], "name": (s.get("name") or "")[:18],
            "status": s.get("status"),
            "d_a": ra["delta_pct"], "t_a": ra["t"], "n_a": ra["n_stocks"] if "n_stocks" in ra else None,
            "d_b": rb["delta_pct"], "t_b": rb["t"],
            "grade": st.get("grade"), "scope": st.get("scope"),
        })
        print(f"  {s['id']} A={ra['delta_pct']:+.3f}/t{ra['t']:+.2f} "
              f"B={rb['delta_pct']:+.3f}/t{rb['t']:+.2f}", flush=True)

    _report(rows)
    OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(OUT_DIR, exist_ok=True)
    p = os.path.join(OUT_DIR, "two_pool.json")
    json.dump(rows, open(p, "w"), ensure_ascii=False, indent=1)
    print(f"\n明细已写入 {p}")
    return 0


def _fg_of(sig, univ, h, tgt):
    ps = qstab._prep(sig, univ, h, tgt)
    p = qstab._fg(ps)
    return p["F"], p["G"]


def _report(rows):
    print("\n" + "=" * 96)
    print("  真实双池对照 ｜ 池 A = 1,492 只（无大中盘）  池 B = 1,988 只（含大中盘）")
    print("=" * 96)
    print(f"  {'ID':9}{'名称':20}{'池A Δ':12}{'池B Δ':12}{'符号':6}{'显著跳变':10}{'stab判级':14}预判")

    flips = []
    misses = []
    for r in sorted(rows, key=lambda x: (x["grade"] or "", x["id"])):
        sign_flip = (r["d_a"] > 0) != (r["d_b"] > 0)
        sig_a = abs(r["t_a"]) >= 1.65
        sig_b = abs(r["t_b"]) >= 1.65
        sig_jump = sig_a != sig_b
        changed = sign_flip or sig_jump
        grade = r["grade"] or "—"
        # 判级是否"预警"了改口：FRAGILE/UNSTABLE/SPLIT 都算预警
        warned = grade in ("FRAGILE", "UNSTABLE") or r["scope"] in ("SPLIT", "CONCENTRATED")
        verdict = ""
        if changed and warned:
            verdict = "✓ 预警"
        elif changed and not warned:
            verdict = "✗ 漏报"
            misses.append(r)
        elif not changed and not warned:
            verdict = "✓ 未改口"
        else:
            verdict = "（预警但未改口）"
        if changed:
            flips.append(r)
        print(f"  {r['id']:9}{r['name']:20}{r['d_a']:+10.3f}pct{r['d_b']:+10.3f}pct"
              f"{'✗翻' if sign_flip else '同号':6}{'是' if sig_jump else '—':10}"
              f"{grade + '/' + (r['scope'] or '') :14}{verdict}")

    print(f"\n  两池之间主口径改口 {len(flips)} 条 / {len(rows)} 条")
    if misses:
        print(f"  ⚠ 漏报 {len(misses)} 条："
              + "、".join(f"{m['id']}({m['grade']}/{m['scope']})" for m in misses))
    else:
        print("  ✓ 所有改口都被判级提前标出（没有'看起来稳却改口'的漏网）")


if __name__ == "__main__":
    raise SystemExit(main())
