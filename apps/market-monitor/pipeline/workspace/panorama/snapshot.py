"""把当日横截面固化成快照，供次日对比。

日更的价值不在「每天重算一遍」，而在「今天和昨天有什么不同」。
没有快照，日更退化成每天重印一份看起来一样的报告。
"""
import json
import os

import pandas as pd

from asof import asof_iso

D = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(D, "data")
SNAP = os.path.join(D, "snapshot")

KEEP = ["symbol", "sw1", "price", "pe", "pb", "composite", "upside", "disp", "disp_pct",
        "n_methods", "label", "quad", "q_pct", "s_value", "s_growth", "s_cyclical",
        "s_dividend", "s_momentum", "s_quality", "resonance", "oneoff", "ind_pe_med",
        "mktcap", "div_yield", "roe_ann"]


def main():
    os.makedirs(SNAP, exist_ok=True)
    m = pd.read_parquet(os.path.join(DATA, "master_full.parquet"))
    m["symbol"] = m["symbol"].astype(str).str.zfill(6)

    names = {}
    p = os.path.join(DATA, "code_name.csv")
    if os.path.exists(p):
        cn = pd.read_csv(p, dtype={"code": str})
        cn["code"] = cn["code"].str.zfill(6)
        names.update(dict(zip(cn["code"], cn["name"].astype(str))))
    meta = json.load(open(os.path.expanduser("~/MarketData/meta.json")))["stocks"]
    for k, v in meta.items():
        nm = str(v.get("name") or "").strip()
        if nm and not names.get(k[:6]):
            names[k[:6]] = nm

    snap = m[[c for c in KEEP if c in m.columns]].copy()
    snap["name"] = snap["symbol"].map(names).fillna("")
    snap["mktcap_yi"] = (snap["mktcap"] / 1e8).round(1)
    snap = snap.drop(columns=["mktcap"])

    asof = asof_iso()
    tag = asof.replace("-", "")
    snap.to_parquet(os.path.join(SNAP, "%s.parquet" % tag), index=False)

    mk = os.path.join(DATA, "market.json")
    if os.path.exists(mk):
        with open(mk) as f:
            market = json.load(f)
        with open(os.path.join(SNAP, "market_%s.json" % tag), "w") as f:
            json.dump({"asof": asof, **market}, f, ensure_ascii=False)

    idx_p = os.path.join(SNAP, "index.json")
    idx = []
    if os.path.exists(idx_p):
        with open(idx_p) as f:
            idx = json.load(f)
    days = sorted({d.get("date", "") for d in idx} | {asof})
    days = [d for d in days if d]
    idx = [{"date": d, "file": "%s.parquet" % d.replace("-", "")} for d in days]
    with open(idx_p, "w") as f:
        json.dump(idx[-60:], f, ensure_ascii=False, indent=1)

    print("快照 %s：%d 只 → snapshot/%s.parquet（历史 %d 天）"
          % (asof, len(snap), tag, len(idx)))


if __name__ == "__main__":
    main()
