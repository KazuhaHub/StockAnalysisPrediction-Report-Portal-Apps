"""两源口径对账：akshare(hfq) 与库内 close 的比值是常数还是随时间漂移？

若比值恒定 → 只差一个复权基准常数，可以整体重定基后换源；
若漂移     → 两者对分红的处理不同，换源会在切换日造出假跳变，绝不能混用。

顺带查：退市股 akshare 有没有、成交量单位是否一致。
"""
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, "/opt/daily-tasks/MarketData")

import akshare as ak
import market_data as md

DATES = ["2016-01-05", "2019-01-03", "2022-01-05", "2026-11-09"]
CODES = ["000001", "600519", "002487", "601138"]


def ratio_table(code):
    row = []
    for d in DATES:
        try:
            lib = md.load(codes=[code], start=d, end=d, as_datetime=False)
            libc = float(lib["close"].iloc[0]) if len(lib) else None
        except Exception:
            libc = None
        try:
            dd = d.replace("-", "")
            df = ak.stock_zh_a_hist(symbol=code, period="daily",
                                    start_date=dd, end_date=dd, adjust="hfq")
            akc = float(df["收盘"].iloc[-1]) if len(df) else None
        except Exception:
            akc = None
        row.append((d, libc, akc, (akc / libc) if libc and akc else None))
    return row


print("== 比值漂移检查（ak / 库）==")
for c in CODES:
    r = ratio_table(c)
    s = "  ".join(f"{d[:4]}:{v:.4f}" if v else f"{d[:4]}:--" for d, _, _, v in r)
    print(f"{c}  {s}")
    vals = [v for _, _, _, v in r if v]
    if len(vals) >= 2:
        print(f"        比值极差 {(max(vals) - min(vals)) / min(vals) * 100:.2f}%  "
              f"→ {'漂移，不可混用' if (max(vals) - min(vals)) / min(vals) > 0.002 else '近似常数'}")

print("\n== 退市股在 akshare 里的可获取性 ==")
meta = md._read_meta()["stocks"]
dead = [c for c, v in meta.items() if v.get("status") == "delisted"][:5]
for c in dead:
    try:
        df = ak.stock_zh_a_hist(symbol=c, period="daily",
                                start_date="20240101", end_date="20261231", adjust="hfq")
        print(f"{c}  根数 {len(df):>4}  末行 "
              f"{df['日期'].iloc[-1] if len(df) else '空'}")
    except Exception as e:
        print(f"{c}  失败 {type(e).__name__}: {str(e)[:60]}")

print("\n== 成交量/成交额单位 ==")
df = ak.stock_zh_a_hist(symbol="000001", period="daily",
                        start_date="20261109", end_date="20261109", adjust="hfq")
print("akshare 列：", list(df.columns))
print("akshare 行：", df.iloc[-1].to_dict())
lib = md.load(codes=["000001"], start="2026-11-09", end="2026-11-09", as_datetime=False)
print("库        行：", lib.iloc[-1][["volume", "amount"]].to_dict())
