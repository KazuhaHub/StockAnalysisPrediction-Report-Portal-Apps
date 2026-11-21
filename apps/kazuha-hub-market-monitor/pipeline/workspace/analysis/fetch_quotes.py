"""拉取指数与重点ETF日线（腾讯行情源），落地为 parquet/csv，供事件研究使用。"""
import json, os, sys, time
import urllib.request

OUT = "/opt/daily-tasks/workspace/analysis/out"
os.makedirs(OUT, exist_ok=True)

CODES = {
    "sh000001": "上证综指",
    "sh000300": "沪深300",
    "sh000905": "中证500",
    "sh000852": "中证1000",
    "sh000688": "科创50",
    "sz399006": "创业板指",
    "sh510300": "沪深300ETF华泰柏瑞",
    "sh510310": "沪深300ETF易方达",
    "sh510050": "上证50ETF华夏",
    "sh588000": "科创50ETF华夏",
    "sz159915": "创业板ETF易方达",
}


def fetch(code, start="2023-10-01", end="2026-11-20", n=900):
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
           f"param={code},day,{start},{end},{n},qfq")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read().decode())
    node = d["data"][code]
    rows = node.get("qfqday") or node.get("day")
    out = []
    for x in rows:
        # [date, open, close, high, low, volume]
        out.append({"date": x[0], "open": float(x[1]), "close": float(x[2]),
                    "high": float(x[3]), "low": float(x[4]), "volume": float(x[5])})
    return out


if __name__ == "__main__":
    res = {}
    for c, n in CODES.items():
        for attempt in range(4):
            try:
                res[c] = {"name": n, "bars": fetch(c)}
                print(f"{c} {n}: {len(res[c]['bars'])} bars "
                      f"{res[c]['bars'][0]['date']}~{res[c]['bars'][-1]['date']}")
                break
            except Exception as e:
                print(f"{c} fail({attempt}): {e}", file=sys.stderr)
                time.sleep(1.5)
        time.sleep(0.3)
    with open(f"{OUT}/quotes.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)
    print("saved", f"{OUT}/quotes.json")
