"""统一的「数据截止日」单一出口。

以前 ASOF 在 build_master / health / compute / fetch_panel / build_data 里各写一份，
日更时必然会漏改一处，结果是拿旧数据算出一份看起来全新的报告，且不报错。
现在全部由本地行情库最后一根 K 线推导，或用环境变量 PANORAMA_ASOF 显式覆盖。
"""
import glob
import json
import os

MD = os.path.expanduser("~/MarketData")
HERE = os.path.dirname(os.path.abspath(__file__))


def last_bar_date():
    files = sorted(glob.glob(os.path.join(MD, "bars", "*.parquet")))
    if not files:
        raise SystemExit("找不到 ~/MarketData/bars/*.parquet，先跑行情库 update")
    import pandas as pd

    df = pd.read_parquet(files[-1], columns=["date"])
    return str(df["date"].astype(str).max())[:10]


def asof_iso():
    return os.environ.get("PANORAMA_ASOF") or last_bar_date()


def asof_compact():
    return asof_iso().replace("-", "")


def report_period(panel_path=None):
    """PIT 面板里最新的报告期，返回 (标签, period)，如 ("2026Q3", "20260930")。"""
    p = panel_path or os.path.join(HERE, "data", "panel.json")
    rp = "20260930"
    if os.path.exists(p):
        with open(p) as f:
            rows = json.load(f)
        cand = [str(r["report_period"]) for r in rows if r.get("report_period")]
        if cand:
            rp = max(cand)
    m = int(rp[4:6])
    return "%sQ%d" % (rp[:4], (m - 1) // 3 + 1), rp


if __name__ == "__main__":
    print("asof      ", asof_iso())
    print("compact   ", asof_compact())
    lab, rp = report_period()
    print("period    ", lab, rp)
