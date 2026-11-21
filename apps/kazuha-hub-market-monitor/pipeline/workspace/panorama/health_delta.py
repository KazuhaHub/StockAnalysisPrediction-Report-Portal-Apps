# -*- coding: utf-8 -*-
"""补票前后的因子体检对照：IC 变了多少，是因子变了还是样本变了。

判读规则（写在输出里，避免自欺）：
  · 截面宽度中位数变化 >20% → 这轮差异主要是"样本换了"，不是"因子换了"；
  · 方向翻转（正负号变了）→ 该因子的结论不稳健，不能写进结论页；
  · 幅度变化但方向不变 → 结论成立，只是强度要按新数报。
"""
import json
import os
import sys

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OLD = os.path.join(D, "health_before_20261114.json")
NEW = os.path.join(D, "health.json")


def load(p):
    return json.load(open(p, encoding="utf-8"))


def main() -> int:
    if not (os.path.exists(OLD) and os.path.exists(NEW)):
        print("缺文件：需要 data/health_before_20261114.json 与 data/health.json")
        return 1
    a, b = load(OLD), load(NEW)

    def wmed(h):
        ws = sorted(x["n"] for x in h.get("width") or [])
        return ws[len(ws) // 2] if ws else None

    wa, wb = wmed(a), wmed(b)
    print(f"截面宽度中位数：补票前 {wa} → 补票后 {wb}"
          + (f"（{(wb / wa - 1) * 100:+.0f}%）" if wa and wb else ""))
    print(f"样本库票数：{a.get('n_codes', '?')} → {b.get('n_codes', '?')}\n")

    hdr = f"{'因子':<10}{'IC20 前':>9}{'IC20 后':>9}{'Δ':>8}{'胜率前':>8}{'胜率后':>8}{'IC60 前':>9}{'IC60 后':>9}"
    print(hdr)
    print("-" * len(hdr))
    flip = []
    for k in b["factors"]:
        oa, ob = a["factors"].get(k), b["factors"][k]
        if not oa:
            continue
        d = (ob["ic20_mean"] or 0) - (oa["ic20_mean"] or 0)
        if (oa["ic20_mean"] or 0) * (ob["ic20_mean"] or 0) < 0:
            flip.append(k)
        print(f"{k:<10}{oa['ic20_mean']:>+9.4f}{ob['ic20_mean']:>+9.4f}{d:>+8.4f}"
              f"{oa['ic20_win'] * 100:>7.0f}%{ob['ic20_win'] * 100:>7.0f}%"
              f"{oa['ic60_mean']:>+9.4f}{ob['ic60_mean']:>+9.4f}")

    ma, mb = a["momentum_summary"], b["momentum_summary"]
    print(f"\n动量五分层 Q5−Q1：{ma.get('Q5_Q1'):+.2f}pp → {mb.get('Q5_Q1'):+.2f}pp"
          f" ｜ 单调性 {ma.get('mono')} → {mb.get('mono')}")
    print("分层均值（%）：" + " ".join(
        f"{k} {ma.get(k):+.2f}→{mb.get(k):+.2f}" for k in ("Q1", "Q2", "Q3", "Q4", "Q5")))
    if flip:
        print(f"\n⚠ 方向翻转：{', '.join(flip)} —— 这些因子不能进结论页，只能写'口径敏感'。")
    else:
        print("\n无方向翻转：本轮差异可解释为样本扩容，因子结论方向不变。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
