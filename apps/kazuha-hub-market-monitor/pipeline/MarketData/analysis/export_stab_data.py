"""导出稳定性报告的图表数据。所有数字从引擎现跑，不手抄。"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.expanduser(
    "~/.workbuddy/skills/quant-signal-research/scripts"))

import qdata  # noqa: E402
import qstab  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
OUT = os.path.join(OUT_DIR, "stab_chart_data.json")


def main() -> int:
    reg = json.load(open(os.path.expanduser(
        "~/.workbuddy/skills/quant-signal-research/registry/signals.json"),
        encoding="utf-8"))["signals"]
    univ = qdata.load_universe(start="2018-01-01", verbose=False)
    targets = [s for s in reg if s.get("status") != "retired" and not s.get("events_file")]

    results = []
    for s in targets:
        r = qstab.run_stability(s, univ, n_boot=40)
        results.append(r)
        print(f"  {r.get('id')} {r.get('grade')}/{r.get('scope')}", flush=True)

    # 双池对照
    two = json.load(open(os.path.join(OUT_DIR, "two_pool.json"), encoding="utf-8"))
    two_map = {r["id"]: r for r in two}

    rows = []
    for r in results:
        if not r.get("full"):
            continue
        tw = two_map.get(r["id"]) or {}
        rows.append({
            "id": r["id"],
            "name": (r.get("name") or "")[:16],
            "status": next((s.get("status") for s in targets if s["id"] == r["id"]), ""),
            "grade": r.get("grade"),
            "scope": r.get("scope"),
            "full_delta": round(r["full"]["delta_pct"], 3),
            "full_t": round(r["full"]["t"], 2),
            "sign_agree": r.get("sign_agree"),
            "sig_rate": r.get("sig_rate"),
            "curve": [{"size": b["size"], "delta": round(b["delta_med"], 3),
                       "t": round(b["t_med"], 2), "sig": round(b["sig_rate"], 3),
                       "match": b["sign_match"]}
                      for b in r.get("curve") or [] if not b.get("skip")],
            "blocks": {k: {n: {"n": v["n_stocks"], "delta": round(v["delta_pct"], 3),
                               "t": round(v["t"], 2)}
                           for n, v in rs.items()}
                       for k, rs in (r.get("blocks") or {}).items()},
            "pool_a": tw.get("d_a"),
            "pool_b": tw.get("d_b"),
        })

    # 双池改口统计
    flips = []
    for row in rows:
        a, b = row.get("pool_a"), row.get("pool_b")
        if a is None or b is None:
            continue
        if (a > 0) != (b > 0):
            flips.append({"id": row["id"], "kind": "符号翻转",
                          "a": round(a, 3), "b": round(b, 3)})
        elif abs(abs(a) - abs(b)) >= 0.15:
            flips.append({"id": row["id"], "kind": "幅度剧变",
                          "a": round(a, 3), "b": round(b, 3)})

    payload = {
        "n_stocks": len(univ),
        "rows": rows,
        "flips": flips,
        "grade_count": {g: sum(1 for r in rows if r["grade"] == g)
                        for g in ("STABLE", "FRAGILE", "UNSTABLE")},
        "scope_count": {s: sum(1 for r in rows if r["scope"] == s)
                        for s in ("BROAD", "CONCENTRATED", "SPLIT", "UNKNOWN")},
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    json.dump(payload, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"\n→ {OUT}  行数 {len(rows)}  改口 {len(flips)}")
    print("grade", payload["grade_count"])
    print("scope", payload["scope_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
