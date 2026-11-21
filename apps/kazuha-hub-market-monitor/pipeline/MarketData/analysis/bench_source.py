"""一次性基准：akshare（东财）vs stock-server（本地 8091）取同一只票同样区间的耗时与口径。

跑法：
    /opt/daily-tasks/venv/bin/python3 analysis/bench_source.py

只读，不写库。目的回答"换源能不能把 100 分钟的更新压下来"，
以及换源后 close 是否还和库里的一致（复权基准不同就没法混用）。
"""
import sys
import time

sys.path.insert(0, "/opt/daily-tasks/MarketData")

import market_data as md

CODES = ["000001", "600519", "300750", "002487", "688981", "002594", "601138", "000858"]
DAY = "2026-11-09"


def bench_ss(codes, day):
    """stock-server：单日区间，与 update 走同一条 _fetch_range。"""
    out = {}
    for c in codes:
        t = time.time()
        try:
            r = md._fetch_range(c, day, day)
            n = len(r.get("bars") or [])
            px = (r.get("bars") or [{}])[0].get("c") if n else None
            out[c] = (time.time() - t, n, px, None)
        except Exception as e:
            out[c] = (time.time() - t, 0, None, f"{type(e).__name__}: {str(e)[:60]}")
    return out


def bench_ak(codes, day):
    import akshare as ak

    d = day.replace("-", "")
    out = {}
    for c in codes:
        t = time.time()
        try:
            df = ak.stock_zh_a_hist(symbol=c, period="daily",
                                    start_date=d, end_date=d, adjust="hfq")
            n = len(df)
            px = float(df["收盘"].iloc[-1]) if n else None
            out[c] = (time.time() - t, n, px, None)
        except Exception as e:
            out[c] = (time.time() - t, 0, None, f"{type(e).__name__}: {str(e)[:60]}")
    return out


def main():
    # 库里 11-09 的收盘价，作为口径基准
    ref = md.load(codes=CODES, start=DAY, end=DAY, as_datetime=False)
    ref = {r.code: float(r.close) for r in ref.itertuples()}

    print(f"样本 {len(CODES)} 只，区间 {DAY}，串行单请求\n")
    ss = bench_ss(CODES, DAY)
    ak = bench_ak(CODES, DAY)

    hdr = f"{'code':<8}{'SS秒':>7}{'AK秒':>7}  {'SS根':>4}{'AK根':>4}  {'库close':>10}{'SSclose':>10}{'AKclose':>10}  备注"
    print(hdr)
    print("-" * len(hdr))
    for c in CODES:
        s, a = ss[c], ak[c]
        note = ""
        if s[3]:
            note += f"SS {s[3]} "
        if a[3]:
            note += f"AK {a[3]}"
        print(f"{c:<8}{s[0]:>7.2f}{a[0]:>7.2f}  {s[1]:>4}{a[1]:>4}  "
              f"{ref.get(c, float('nan')):>10.2f}"
              f"{(s[2] if s[2] is not None else float('nan')):>10.2f}"
              f"{(a[2] if a[2] is not None else float('nan')):>10.2f}  {note}")

    def agg(x):
        ok = [v for v in x.values() if v[3] is None]
        return (sum(v[0] for v in ok) / len(ok)) if ok else float("nan"), len(ok)

    ss_avg, ss_ok = agg(ss)
    ak_avg, ak_ok = agg(ak)
    print(f"\n成功 {ss_ok}/{len(CODES)} vs {ak_ok}/{len(CODES)}；单请求均值 "
          f"SS {ss_avg:.2f}s / AK {ak_avg:.2f}s（比值 {ak_avg / ss_avg:.2f}×）")
    print(f"外推 3,330 只 × 6 并发：SS {3330 * ss_avg / 6 / 60:.0f} 分钟 / "
          f"AK {3330 * ak_avg / 6 / 60:.0f} 分钟")

    # 与库内 close 的一致性（同一天、后复权）
    for name, res in (("SS", ss), ("AK", ak)):
        diff = [(c, ref[c], res[c][2]) for c in CODES
                if c in ref and res[c][2] is not None]
        if diff:
            bad = [(c, a, b, (b - a) / a * 100) for c, a, b in diff if abs(b - a) > 0.005]
            print(f"{name} 与库 close 不一致的 {len(bad)}/{len(diff)} 只", end="")
            if bad:
                print("：" + "; ".join(f"{c} {a:.2f}→{b:.2f}({p:+.2f}%)" for c, a, b, p in bad[:5]))
            else:
                print()


if __name__ == "__main__":
    main()
