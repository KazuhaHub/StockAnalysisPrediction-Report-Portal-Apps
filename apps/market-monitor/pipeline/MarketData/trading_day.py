"""最近交易日：给 update.sh 定终点用。

为什么需要它
  `market_data.py update` 默认 end=今天。周六手跑一次，4,276 只票全被判成「待更新」，
  每只都去源端要 11-14 的 K 线、拿回 0 行——实测 2 秒/只，白烧 2.4 小时上游额度，
  还把同一台服务器上的补票任务一起拖进 429。把 end 换成「最近交易日」就没事：
  库里已经是 11-13 的票直接算「已最新」，一轮 3 秒收工。

口径
  服务端 `/api/v1/calendar/trading` 按交易所给日历（SSE/SZSE 交易日一致），
  `/previous` 那个端点现在返回 500，所以取区间再挑最大。
  取不到就返回非零退出码，调用方退回「今天」，行为与改造前一致，不会更糟。
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta

BASE = os.environ.get("QUOTE_API", "https://quotes.internal.anchan.kazuhahub.com") + "/api/v1/calendar/trading"


def last_trading_day(upto=None, lookback=20):
    upto = upto or date.today().isoformat()
    start = (date.fromisoformat(upto) - timedelta(days=lookback)).isoformat()
    q = urllib.parse.urlencode({"exchange": "SSE", "start_date": start, "end_date": upto})
    rows = json.load(urllib.request.urlopen(BASE + "?" + q, timeout=30))
    ds = sorted(str(r.get("date"))[:10] for r in rows if r.get("is_trading_day"))
    return ds[-1] if ds else None


if __name__ == "__main__":
    try:
        d = last_trading_day(sys.argv[1] if len(sys.argv) > 1 else None)
    except Exception as e:  # 网络/接口变了都不该拦住日更
        print("ERR %s" % type(e).__name__, file=sys.stderr)
        sys.exit(1)
    if not d:
        print("ERR 日历里没有交易日", file=sys.stderr)
        sys.exit(1)
    print(d)
