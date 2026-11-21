"""对比最近两个交易日的快照，产出「今日变化」。

只回答四个问题：
1. 市场整体口径动了多少（中位 PE/PB、宽度）
2. 估值标签怎么迁移（昨天合理今天变什么的）
3. 各榜单谁进谁出（上涨空间 Top50、六策略 Top50）
4. 谁的上涨空间位移最大（不论进出，位移本身就是信号）
"""
import json
import os

import pandas as pd

D = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(D, "snapshot")
DATA = os.path.join(D, "data")

LABELS = ["显著低估", "低估", "合理", "高估", "显著高估", "单一方法参考", "分歧过大", "数据不足"]
STRATS = [("s_value", "价值"), ("s_growth", "成长"), ("s_cyclical", "周期"),
          ("s_dividend", "红利"), ("s_momentum", "动量"), ("s_quality", "质量")]
TOP = 50


def load(path):
    df = pd.read_parquet(path)
    df["symbol"] = df["symbol"].astype(str).str.zfill(6)
    return df.set_index("symbol")


def top_list(df, col, by="desc"):
    d = df[df[col].notna()] if col in df.columns else df.iloc[0:0]
    return list(d.sort_values(col, ascending=(by == "asc")).head(TOP).index)


def main():
    idx_p = os.path.join(SNAP, "index.json")
    empty = {"first": True, "cur": None, "prev": None}
    if not os.path.exists(idx_p):
        json.dump(empty, open(os.path.join(DATA, "diff.json"), "w"), ensure_ascii=False)
        print("无快照，diff 置空")
        return
    idx = json.load(open(idx_p))
    if len(idx) < 2:
        cur = idx[-1]["date"] if idx else None
        json.dump({"first": True, "cur": cur, "prev": None},
                  open(os.path.join(DATA, "diff.json"), "w"), ensure_ascii=False)
        print("只有 %d 天快照，首日无对比基线" % len(idx))
        return

    prev_d, cur_d = idx[-2]["date"], idx[-1]["date"]
    a = load(os.path.join(SNAP, idx[-2]["file"]))
    b = load(os.path.join(SNAP, idx[-1]["file"]))
    common = a.index.intersection(b.index)
    A, B = a.loc[common], b.loc[common]
    # 可比样本 = 两日都给出上涨空间的股票。只算「两日都有行」会把
    # 当天缺价、没有估值结论的标的也算进分母，位移率会被人为稀释。
    comp = A.index[A["upside"].notna() & B["upside"].notna()]
    A, B = A.loc[comp], B.loc[comp]

    # 1 标签迁移矩阵
    la = A["label"].fillna("数据不足")
    lb = B["label"].fillna("数据不足")
    mat = [[int(((la == x) & (lb == y)).sum()) for y in LABELS] for x in LABELS]

    # 2 市场口径
    def agg(snap, tag):
        p = os.path.join(SNAP, "market_%s.json" % snap.replace("-", ""))
        return json.load(open(p)) if os.path.exists(p) else {}

    ma, mb = agg(prev_d, "a"), agg(cur_d, "b")
    keys = [("median_pe", "中位 PE", 1), ("median_pb", "中位 PB", 2),
            ("above_ma120_pct", "站上 120MA", 1), ("above_ma250_pct", "站上 250MA", 1)]
    market = []
    for k, lab, dg in keys:
        v0, v1 = ma.get(k), mb.get(k)
        if v0 is None or v1 is None:
            continue
        market.append({"k": lab, "v0": round(v0, dg), "v1": round(v1, dg), "d": round(v1 - v0, dg)})

    # 3 榜单进出
    def board(col, name):
        ia, ib = set(top_list(A, col)), set(top_list(B, col))
        name_map = B["name"] if "name" in B.columns else pd.Series("", index=B.index)
        return {
            "name": name,
            "in": [{"s": s, "n": str(name_map.get(s, "")), "v": _num(B.at[s, col])}
                   for s in sorted(ib - ia, key=lambda x: -(B.at[x, col] or 0))][:12],
            "out": [{"s": s, "n": str(name_map.get(s, "")), "v": _num(A.at[s, col])}
                    for s in sorted(ia - ib, key=lambda x: -(A.at[x, col] or 0))][:12],
            "n_in": len(ib - ia), "n_out": len(ia - ib),
        }

    boards = [board("upside", "上涨空间")] + [board(c, n2) for c, n2 in STRATS]

    # 4 位移最大
    # 位移榜只用方法数 >=3 的标的：单一方法给出的极端上涨空间每天乱跳，
    # 排在最上面会把真正的估值修正挡住。
    _ok = (A["n_methods"].fillna(0) >= 3) & (B["n_methods"].fillna(0) >= 3)
    du_all = (B["upside"] - A["upside"]).dropna()
    du = (B.loc[_ok, "upside"] - A.loc[_ok, "upside"]).dropna()
    shift = []
    nm = B["name"] if "name" in B.columns else pd.Series("", index=B.index)
    for s in du.abs().sort_values(ascending=False).head(15).index:
        shift.append({"s": s, "n": str(nm.get(s, "")), "a": _num(A.at[s, "upside"]),
                      "b": _num(B.at[s, "upside"]), "d": _num(du[s]),
                      "la": str(A.at[s, "label"]), "lb": str(B.at[s, "label"])})

    # 5 标签净变化
    net = []
    for l in LABELS:
        c0 = int((A["label"].fillna("数据不足") == l).sum())
        c1 = int((B["label"].fillna("数据不足") == l).sum())
        net.append({"k": l, "a": c0, "b": c1, "d": c1 - c0})
    net = [x for x in net if x["a"] or x["b"]]

    moved_up = int((du_all > 0.02).sum())
    moved_dn = int((du_all < -0.02).sum())
    out = {
        "first": False, "prev": prev_d, "cur": cur_d,
        "n_prev": int(len(a)), "n_cur": int(len(b)),
        "n_overlap": int(len(common)), "n_comp": int(len(comp)),
        "labels": LABELS, "matrix": mat,
        "market": market, "boards": boards, "shift": shift, "net": net,
        "pool_prev": int(a["upside"].notna().sum()), "pool_cur": int(b["upside"].notna().sum()),
        "moves": {"up": moved_up, "down": moved_dn,
                  "same": int(len(du_all)) - moved_up - moved_dn,
                  "med_d": _num(du_all.median()) if len(du_all) else None},
    }
    json.dump(out, open(os.path.join(DATA, "diff.json"), "w"), ensure_ascii=False)
    print("对比 %s → %s：可比 %d 只（两日都有结论），上涨空间上移 %d / 下移 %d，中位位移 %s"
          % (prev_d, cur_d, len(comp), moved_up, moved_dn, out["moves"]["med_d"]))


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else round(f, 4)


if __name__ == "__main__":
    main()
