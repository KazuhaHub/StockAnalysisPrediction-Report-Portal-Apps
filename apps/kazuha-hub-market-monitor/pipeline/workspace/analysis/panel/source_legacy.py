#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据层：抓取源站 data.js + 腾讯实时行情，落盘到 data/latest.json。

用法：
    python3 source.py            # 抓取并落盘，失败时保留旧快照并返回非零
    python3 source.py --check    # 只检查源站是否可用

口径说明：
  · 净流入 = ETF 申赎口径（源站 Choice 数据），单位亿元；
  · 实时行情 = 腾讯财经（qt.gtimg.cn），成交额为当日累计，单位亿元；
  · 上证分时 = 腾讯 minute/query，含当日每分钟点位与累计成交额。
"""
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
BASE = "https://jinke.app.workbuddy.host"
SHARE = os.environ.get("LEGACY_SHARE_CODE", "")
PWD = os.environ.get("LEGACY_SHARE_PASSWORD", "")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


class AuthError(RuntimeError):
    pass


def _req(url, data=None, cookie=None, timeout=20):
    req = urllib.request.Request(url, data=data)
    req.add_header("User-Agent", UA)
    if data:
        req.add_header("Content-Type", "application/json")
    if cookie:
        req.add_header("Cookie", cookie)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_islands():
    """登录并解析 window.__ISLANDS。解析失败或密码被拒均抛异常。"""
    root = "%s/?sharecode=%s" % (BASE, SHARE)
    try:
        _req(root)
    except Exception:
        pass

    body = json.dumps({"password": PWD}).encode()
    resp = _req("%s/api/verify?sharecode=%s" % (BASE, SHARE), data=body)
    try:
        ok = json.loads(resp.decode("utf-8", "ignore")).get("ok")
    except Exception:
        ok = None
    if not ok:
        raise AuthError("源站 /api/verify 返回 ok=false（密码被拒或链接已重新发布）")

    js = _req("%s/data.js?sharecode=%s" % (BASE, SHARE)).decode("utf-8", "ignore")
    if "__ISLANDS" not in js:
        raise AuthError("data.js 返回的不是数据（长度 %d），未通过鉴权" % len(js))

    i = js.index("window.__ISLANDS")
    obj = js[js.index("{", i):].rstrip().rstrip(";")
    # 交给 node 解析 JS 对象字面量，避免自己写容错解析器
    out = subprocess.run(
        ["node", "-e",
         "const fs=require('fs');const s=fs.readFileSync(0,'utf8');"
         "const o=eval('('+s+')');process.stdout.write(JSON.stringify(o));"],
        input=obj.encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    if out.returncode != 0:
        raise RuntimeError("node 解析失败: " + out.stderr.decode()[:200])
    return json.loads(out.stdout.decode())


def fetch_quotes(codes):
    """腾讯批量报价。返回 [{code,name,price,prev,pct,amount_yi}]。"""
    if not codes:
        return []
    qs = ",".join(("sh" if c[0] in "56" else "sz") + c for c in codes)
    raw = _req("https://qt.gtimg.cn/q=" + qs).decode("gbk", "ignore")
    rows = []
    for line in raw.strip().split(";"):
        line = line.strip()
        if not line.startswith("v_"):
            continue
        f = line.split("=", 1)[1].strip('"').split("~")
        if len(f) < 40:
            continue
        try:
            rows.append({
                "code": f[2],
                "name": f[1],
                "price": float(f[3]),
                "prev": float(f[4]),
                "pct": float(f[32]),
                "amount_yi": round(float(f[37]) / 10000.0, 2),
                "high": float(f[33]),
                "low": float(f[34]),
                "time": f[30],
            })
        except Exception:
            continue
    return rows


def fetch_index_minute(code="sh000001"):
    """当日上证分时：times / prices / amount_yi(累计)。"""
    raw = _req("https://web.ifzq.gtimg.cn/appstock/app/minute/query?code=" + code)
    d = json.loads(raw.decode("utf-8", "ignore"))
    node = d.get("data", {}).get(code, {})
    inner = node.get("data") if isinstance(node.get("data"), dict) else {}
    day = inner.get("date") or node.get("date") or ""
    rows = inner.get("data") or node.get("data") or []
    rows = [r for r in rows if isinstance(r, str)]
    times, prices, amt = [], [], []
    for r in rows:
        p = r.split()
        if len(p) < 4:
            continue
        hhmm = p[0]
        times.append("%s:%s" % (hhmm[:2], hhmm[2:]))
        prices.append(float(p[1]))
        amt.append(round(float(p[3]) / 1e8, 2))
    return {"code": code, "date": day, "times": times, "prices": prices, "amount_yi": amt}


def fetch_index_daily(code="sh000001", start="2026-01-01"):
    """上证日线（用于把体检指标推进到最新交易日）。"""
    q = "%s,day,%s,2050-01-01,400,qfq" % (code, start)
    raw = _req("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=" + q)
    d = json.loads(raw.decode("utf-8", "ignore"))
    node = d.get("data", {}).get(code, {})
    rows = node.get("qfqday") or node.get("day") or []
    bars = []
    for r in rows:
        try:
            bars.append({"date": r[0], "open": float(r[1]), "close": float(r[2]),
                         "high": float(r[3]), "low": float(r[4])})
        except Exception:
            continue
    return bars


def main():
    check_only = "--check" in sys.argv
    os.makedirs(DATA, exist_ok=True)
    latest = os.path.join(DATA, "latest.json")

    old = {}
    if os.path.exists(latest):
        old = json.load(open(latest, encoding="utf-8"))

    try:
        snap = fetch_islands()
        src_state = "ok"
        src_err = ""
    except Exception as e:
        src_state = "fail"
        src_err = str(e)
        snap = old.get("snapshot")
        print("[source] 源站抓取失败：%s" % src_err, file=sys.stderr)

    if check_only:
        print(json.dumps({"source": src_state, "error": src_err}, ensure_ascii=False))
        return 0 if src_state == "ok" else 2

    codes = []
    if snap:
        codes = [f["code"] for f in (snap.get("histData", {}).get("funds") or [])]
    quotes, index_minute, live_err = [], {}, ""
    try:
        quotes = fetch_quotes(codes)
        index_minute = fetch_index_minute()
    except Exception as e:
        live_err = str(e)
        print("[source] 实时行情抓取失败：%s" % live_err, file=sys.stderr)

    try:
        index_daily = fetch_index_daily()
    except Exception as e:
        index_daily = []
        print("[source] 上证日线抓取失败：%s" % e, file=sys.stderr)

    payload = {
        "snapshot": snap,
        "quotes": quotes or old.get("quotes", []),
        "index_minute": index_minute or old.get("index_minute", {}),
        "index_daily": index_daily or old.get("index_daily", []),
        "state": {"source": src_state, "source_err": src_err,
                  "live": "ok" if quotes else "fail", "live_err": live_err},
        "fetched_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    json.dump(payload, open(latest, "w", encoding="utf-8"), ensure_ascii=False)
    print("[source] 已保存 %s（snapshot=%s, quotes=%d）" % (latest, src_state, len(quotes)))
    return 0 if snap else 1


if __name__ == "__main__":
    sys.exit(main())
