#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 web/index.html —— 四份日更报告的汇总入口。

只做一件事：把「文件明明在，但其实是三天前的」这种情况暴露出来。
每张卡片都显示文件更新时间 + 数据基准日，任一滞后就标黄/标红。
"""
import json
import os
import time
from datetime import date, datetime

APP_HOME = os.environ.get("APP_HOME", "/opt/daily-tasks")
WS = os.environ.get("WS_ROOT", os.path.join(APP_HOME, "workspace"))
WEB = os.environ.get("WEB_ROOT", os.path.join(APP_HOME, "web"))

REPORTS = [
    {
        "key": "sentiment.html",
        "name": "市场情绪监控",
        "desc": "五维读数 · 广度×集中度定位 · 极冷信号持续天数",
        "src": os.path.join(WS, "reports/sentiment-monitor/monitor.html"),
        "asof_from": (os.path.join(WS, "analysis/out/sentiment/monitor.json"), ("asof", "base_date", "date")),
        "schedule": "周二至周六 00:40",
    },
    {
        "key": "panorama.html",
        "name": "Panorama 全策略选股",
        "desc": "54 因子 / 六策略 / 十法估值 · 与前一日对比",
        "src": os.path.join(WS, "panorama/Panorama_全策略选股与十法估值.html"),
        "asof_from": (os.path.join(WS, "panorama/data/site_payload.json"), ("meta",)),
        "schedule": "周二至周六 00:50",
    },
    {
        "key": "etf.html",
        "name": "宽基 ETF 资金监测",
        "desc": "份额×净值→净流入 · 事件阈值 100 亿 · 状态灯",
        "src": os.path.join(WS, "reports/ETF国家队资金监测面板.html"),
        "asof_from": (os.path.join(WS, "analysis/panel/data/metrics.json"), ("asof", "date")),
        "schedule": "周二至周六 08:00",
    },
    {
        "key": "margin.html",
        "name": "融资盘·持仓结构扫描",
        "desc": "两融结构 · 成本线共振带 · 风险状态分布",
        "src": os.path.join(APP_HOME, "margin_scan/融资盘与持仓结构扫描.html"),
        "asof_from": (os.path.join(APP_HOME, "margin_scan/out/payload.json"), ("meta", "as_of")),
        "schedule": "周一至周五 09:00",
    },
]


def pick_asof(path, keys):
    """从 json 里挖基准日，字段名各项目不统一，按候选顺序试。"""
    if not os.path.exists(path):
        return ""
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return ""
    for k in keys:
        v = d.get(k) if isinstance(d, dict) else None
        if isinstance(v, dict):
            # 各项目字段名不统一：Panorama 用 meta.asof，融资盘用 meta.as_of
            for kk in ("asof", "as_of", "as_of_date", "date", "trade_date", "generated_at"):
                if v.get(kk):
                    return str(v[kk])[:10]
            continue
        if v:
            return str(v)[:10]
    return ""


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def lag_days(mtime):
    return (date.today() - date.fromtimestamp(mtime)).days


def md_last():
    p = os.path.join(os.environ.get("MD_HOME", os.path.join(APP_HOME, "MarketData")), "meta.json")
    try:
        return json.load(open(p))["date_range"][1]
    except Exception:
        return "—"


def main():
    cards = []
    for r in REPORTS:
        src = r["src"]
        if not os.path.exists(src):
            cards.append({**r, "exists": False})
            continue
        st = os.stat(src)
        asof = pick_asof(*r["asof_from"])
        lag = lag_days(st.st_mtime)
        # 判断「新不新」：优先看数据基准日，取不到才退回文件时间
        if asof:
            try:
                data_lag = (date.today() - date.fromisoformat(asof)).days
            except Exception:
                data_lag = lag
        else:
            data_lag = lag
        state = "ok" if data_lag <= 4 else ("warn" if data_lag <= 7 else "bad")
        cards.append({
            **r, "exists": True, "size": human_size(st.st_size),
            "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%m-%d %H:%M"),
            "asof": asof or "—", "lag": data_lag, "state": state,
        })

    rows = []
    for c in cards:
        if not c["exists"]:
            rows.append(f"""<div class="card bad"><div class="hd"><span class="dot"></span>{c['name']}</div>
<div class="desc">{c['desc']}</div><div class="meta">尚未生成 · 计划 {c['schedule']}</div></div>""")
            continue
        dot = {"ok": "ok", "warn": "warn", "bad": "bad"}[c["state"]]
        lag_txt = "" if c["lag"] <= 4 else f"（滞后 {c['lag']} 天）"
        rows.append(f"""<div class="card {c['state']}"><div class="hd"><span class="dot {dot}"></span>{c['name']}</div>
<div class="desc">{c['desc']}</div>
<div class="meta">数据基准日 <b>{c['asof']}</b>{lag_txt}<br>文件 {c['mtime']} · {c['size']}</div>
<a href="{c['key']}">打开 →</a></div>""")

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>日更看板</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--line:#e3e6ea;--txt:#1a1d21;--sub:#6b7280;
--ok:#0f9d58;--warn:#d97706;--bad:#dc2626;--accent:#b4232c}}
*{{box-sizing:border-box}}
body{{margin:0;padding:32px 20px 60px;background:var(--bg);color:var(--txt);
font:15px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}}
.wrap{{max-width:1140px;margin:0 auto}}
h1{{font-size:22px;margin:0 0 6px;font-weight:600}}
.sub{{color:var(--sub);font-size:13px;margin-bottom:26px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(232px,1fr));gap:16px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 18px 14px;
display:flex;flex-direction:column;transition:.15s}}
.card:hover{{box-shadow:0 4px 16px rgba(0,0,0,.07);transform:translateY(-1px)}}
.card.warn{{border-color:#f0c987}} .card.bad{{border-color:#f0a7a7}}
.hd{{font-size:16px;font-weight:600;display:flex;align-items:center;gap:8px;margin-bottom:6px}}
.dot{{width:8px;height:8px;border-radius:50%;background:var(--sub);flex:none}}
.dot.ok{{background:var(--ok)}} .dot.warn{{background:var(--warn)}} .dot.bad{{background:var(--bad)}}
.desc{{color:var(--sub);font-size:13px;margin-bottom:12px;flex:1;min-height:2.9em}}
.meta{{font-size:12.5px;color:var(--sub);line-height:1.7;margin-bottom:10px}}
.meta b{{color:var(--txt);font-weight:600}}
a{{color:var(--accent);text-decoration:none;font-size:13.5px;font-weight:500}}
a:hover{{text-decoration:underline}}
.foot{{margin-top:28px;color:var(--sub);font-size:12px;border-top:1px solid var(--line);padding-top:14px}}
</style></head><body><div class="wrap">
<h1>日更看板</h1>
<div class="sub">生成于 {now} · 行情库末端 {md_last()}</div>
<div class="grid">
{chr(10).join(rows)}
</div>
<div class="foot">数据源：本地行情库 + 沪深交易所披露 + 东方财富公开接口。所有页面离线单文件，无外链依赖。</div>
</div></body></html>"""

    out = os.path.join(WEB, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✓ 索引页 {out}")


if __name__ == "__main__":
    main()
