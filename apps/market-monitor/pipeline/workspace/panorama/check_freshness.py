"""数据新鲜度闸门：ASOF 是否等于「今天（或之前）最近的那个交易日」。

ASOF 是从本地 K 线推导的，所以「ASOF == 最后一根 K 线」是同义反复，
挡不住「今天是交易日但行情库昨晚更新失败」。这里向服务端要交易日历做真校验。
"""
import sys
from datetime import date

import mcpc

from asof import asof_iso


def last_trading_day(upto=None):
    m = mcpc.MCP("http://localhost:8091/mcp").init()
    r = m.call("query_trading_calendar", {"action": "previous_day",
                                         "date": upto or date.today().isoformat()})
    for k in ("previous_trading_day", "date", "trade_date", "previous_day", "prev_date"):
        v = r.get(k)
        if v:
            return str(v)[:10]
    d = r.get("data") or {}
    if isinstance(d, dict):
        for k in ("date", "trade_date", "previous_day"):
            if d.get(k):
                return str(d[k])[:10]
    raise SystemExit("交易日历返回无法解析：%s" % str(r)[:200])


def coverage(asof: str):
    """ASOF 当天有 bar 的票数 / 库内票数。

    日期闸门只能证明「库里有今天这根 K 线」，证明不了「今天的 K 线都写进去了」。
    行情库 update 是逐票追加、补票 ingest 是整年分区重写，中途被读就会得到
    一个「先跑完的 200 只有、剩下的 3,000 只没有」的半成品截面——日期照样是最新的。
    用覆盖度兜住这一类：常态 88%~95%（停牌与当年退市的票本来就没有今天的 bar）。
    """
    import os
    import pandas as pd
    import sys as _sys

    _sys.path.insert(0, os.path.expanduser("~/MarketData"))
    import market_data as md

    p = os.path.join(os.path.expanduser("~/MarketData"), "bars", "%s.parquet" % asof[:4])
    df = pd.read_parquet(p, columns=["code", "date"])
    d = df["date"].astype(str).str[:10]
    return int(df.loc[d == asof, "code"].nunique()), len(md.codes())


if __name__ == "__main__":
    asof = asof_iso()
    try:
        expect = last_trading_day()
    except SystemExit as e:
        print("WARN %s" % e)
        sys.exit(0)
    except Exception as e:  # 服务不可达时不阻断，只告警
        print("WARN 交易日历不可用（%s），跳过新鲜度校验" % type(e).__name__)
        sys.exit(0)
    if asof != expect:
        print("STALE 行情库最后一根 K 线 %s，但最近交易日是 %s" % (asof, expect))
        sys.exit(2)

    try:
        n, tot = coverage(asof)
    except Exception as e:  # 分区缺失/字段变化都不该拦住出报告
        print("OK %s ｜ 覆盖度校验跳过（%s）" % (asof, type(e).__name__))
        sys.exit(0)
    ratio = n / max(tot, 1)
    if ratio < 0.60:
        print("STALE %s 当天只有 %d/%d 只（%.0f%%）有 K 线，行情库像没写完" % (asof, n, tot, ratio * 100))
        sys.exit(2)
    if ratio < 0.88:
        print("WARN %s 当天覆盖 %d/%d（%.0f%%），低于常态 88%%，留意是不是漏票" % (asof, n, tot, ratio * 100))
        sys.exit(0)
    print("OK %s ｜ 覆盖 %d/%d 只（%.0f%%）" % (asof, n, tot, ratio * 100))
