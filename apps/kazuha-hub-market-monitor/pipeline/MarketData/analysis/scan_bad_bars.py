"""扫 11-10 全库的异常日收益，揪出与"复权因子滞后"同类的票。

思路：先按涨跌停规则筛出超限的票（主板 ±10%、创业板/科创 ±20%、ST ±5%），
再用 akshare 的官方 `涨跌幅` 做仲裁——库内收益与官方一致就是真实行情，
对不上就是库里的 bar 用了旧因子（603596 那种）。
只读，不改库。
"""
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, "/opt/daily-tasks/MarketData")

import akshare as ak
import market_data as md

DAY, PREV = "2026-11-10", "2026-11-09"


def limit_of(code):
    if code.startswith(("300", "301", "688")):
        return 20.0
    return 10.0


df = md.load(start=PREV, end=DAY, as_datetime=False)
piv = df.pivot_table(index="code", columns="date", values="close")
piv = piv.dropna()
piv["ret"] = (piv[DAY] / piv[PREV] - 1) * 100
piv["lim"] = [limit_of(c) for c in piv.index]
cand = piv[abs(piv["ret"]) > piv["lim"] + 0.6].sort_values("ret")
print(f"全库 {len(piv)} 只，超涨跌停的 {len(cand)} 只（含 ST 未单独放宽，会多筛出一些）\n")

rows = []
for c in cand.index:
    try:
        d = ak.stock_zh_a_hist(symbol=c, period="daily",
                               start_date=DAY.replace("-", ""),
                               end_date=DAY.replace("-", ""), adjust="hfq")
        ak_ret = float(d["涨跌幅"].iloc[-1]) if len(d) else None
    except Exception:
        ak_ret = None
    rows.append((c, float(cand.loc[c, "ret"]), ak_ret))

bad = [r for r in rows if r[2] is not None and abs(r[1] - r[2]) > 1.0]
print(f"{'code':<8}{'库内%':>9}{'官方%':>9}{'差':>8}")
for c, a, b in bad:
    print(f"{c:<8}{a:>9.2f}{b:>9.2f}{(a - b):>8.2f}")
print(f"\n对不上的 {len(bad)} / {len(rows)} 只（阈值：差 > 1 个百分点）")
