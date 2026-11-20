#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""渲染层：data/metrics.json → 单文件 HTML 面板。

产出：reports/ETF国家队资金监测面板.html（相对引用 echarts.min.js / chart-boot.js，
由 build_report.py 内联成离线单文件）。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(ROOT, "analysis", "out")
REPORTS = os.path.join(ROOT, "reports")

RED, GREEN = "#c0392b", "#1e8449"


def heat(v, vmax):
    """净流入红绿底：正红负绿，深浅按绝对值/当列最大。"""
    if v is None:
        return ""
    a = min(abs(v) / vmax, 1) if vmax else 0
    if v > 0:
        return "background:rgba(192,57,43,%.2f);color:%s" % (0.06 + 0.58 * a, "#fff" if a > 0.62 else "#8c2b20")
    if v < 0:
        return "background:rgba(30,132,73,%.2f);color:%s" % (0.06 + 0.58 * a, "#fff" if a > 0.62 else "#16603a")
    return ""


def fmt(v, nd=0, sign=False):
    if v is None:
        return "—"
    s = ("%+.*f" if sign else "%.*f") % (nd, v)
    return s


def cls(v):
    return "up" if v > 0 else ("down" if v < 0 else "flat")


def build():
    M = json.load(open(os.path.join(HERE, "data", "metrics.json"), encoding="utf-8"))
    # latest.json 只提供实时行情（腾讯批量报价 + 分时），不再提供净流入
    P = json.load(open(os.path.join(HERE, "data", "latest.json"), encoding="utf-8")) \
        if os.path.exists(os.path.join(HERE, "data", "latest.json")) else {}
    cur, h = M["current"], M["health"]

    # ---- 实时行情 ----
    im = P.get("index_minute") or {}
    px_last = im.get("prices", [])[-1] if im.get("prices") else None
    idx_prev = cur["idx_last"]
    live_pct = (px_last / idx_prev - 1) * 100 if px_last else None
    quotes = sorted(P.get("quotes") or [], key=lambda x: -x["amount_yi"])

    # ---- 盘中数据 ----
    # 与 20 日均值同口径：只累加沪市（5/6 开头），否则深市会把倍数放大
    sh_quotes = [q for q in quotes if q["code"][:1] in "56"]
    amt_today = sum(q["amount_yi"] for q in sh_quotes) if sh_quotes else None
    amt_ma20 = next((v for v in reversed(M["series"]["amt_ma20"]) if v), None)
    minute = {"t": im.get("times", []), "p": im.get("prices", []),
              "prev": cur["idx_last"],
              "amt": round(amt_today, 1) if amt_today else None,
              "ma20": amt_ma20,
              "ratio": round(amt_today / amt_ma20, 2) if (amt_today and amt_ma20) else None}

    # ---- 图表数据 ----
    S = M["series"]
    span = 180
    fund_list = M["funds"]
    chart = {
        "flow": {"d": S["dates"][-span:], "nf": S["nf"][-span:], "idx": S["idx"][-span:]},
        "amt": {"d": S["dates"][-span:], "amt": S["amt"][-span:],
                "ma": S["amt_ma20"][-span:], "nf": S["nf"][-span:]},
        "broad": {"dates": M["broad"]["dates"], "cats": M["broad"]["cats"],
                  "colors": [M["broad"]["colors"].get(c, "#888") for c in M["broad"]["cats"]],
                  "series": M["broad"]["series"], "total": M["broad"]["total"],
                  "cum": M["broad"]["cum"]},
        "cum": {"dates": M["cum_dates"],
                "codes": list(M["cum_series"].keys()),
                "names": M["cum_names"],
                "colors": {c: ["#c0392b", "#e8862e", "#1f4e79", "#1e8449", "#8e44ad"][i % 5]
                           for i, c in enumerate(M["cum_series"].keys())},
                "series": M["cum_series"], "total": [],
                "start": 0},
        "margin": M["margin"],
        "roll": M["roll"],
        "minute": minute,
        "year": [{"year": r["year"],
                  "ex5": r["h5"]["excess"] if r["h5"] else None,
                  "ex20": r["h20"]["excess"] if r["h20"] else None,
                  "n": r["h5"]["n"] if r["h5"] else 0,
                  "t5": r["h5"]["t"] if r["h5"] else None,
                  "t20": r["h20"]["t"] if r["h20"] else None} for r in M["yearly"]],
    }

    # 成交额双相关：方向 vs 强度，2026 年出现「强度极高、方向相反」的背离
    _ad = (M.get("amt_diag") or {}).get("byyear") or []
    chart["amtcorr"] = {"years": [r["year"] for r in _ad],
                        "signed": [r["corr_signed"] for r in _ad],
                        "abs": [r["corr_abs"] for r in _ad]}

    # ---- 最近一月分类矩阵 ----
    bd, bc, bs = M["broad"]["dates"], M["broad"]["cats"], M["broad"]["series"]
    recent = bd[-16:]
    vmax = max(abs(v) for c in bc for v in bs[c][-16:]) or 1
    rows = []
    for c in bc:
        vals = bs[c][-16:]
        tds = "".join('<td class="num" style="%s">%s</td>' % (heat(v, max(abs(x) for x in vals) or 1), fmt(v, 0))
                      for v in vals)
        tot = sum(vals)
        rows.append('<tr><th class="rowh">%s</th>%s<td class="num tot %s">%s</td></tr>'
                    % (c, tds, cls(tot), fmt(tot, 0, True)))
    broad_table = ('<table class="matrix"><thead><tr><th class="rowh">分类</th>%s<th class="num">%d日累计</th></tr></thead>'
                   '<tbody>%s</tbody></table>'
                   % ("".join("<th class=\"num\">%s</th>" % d[5:] for d in recent), len(recent), "".join(rows)))

    # ---- 事件研究表 ----
    ev_rows = []
    for r in M["yearly"]:
        for hh, key in ((5, "h5"), (20, "h20")):
            e = r[key]
            if not e:
                continue
            ev_rows.append(
                "<tr><td>%s</td><td class=\"num\">%d 日</td><td class=\"num\">%d</td><td class=\"num\">%d</td>"
                "<td class=\"num %s\">%s%%</td><td class=\"num\">%s%%</td>"
                "<td class=\"num %s\"><b>%s</b></td><td class=\"num\">%s</td><td class=\"num\">%s</td></tr>"
                % (r["year"], hh, e["n"], e["clusters"], cls(e["mean"]), fmt(e["mean"], 2, True),
                   fmt(e["base"], 2, True), cls(e["excess"]), fmt(e["excess"], 2, True),
                   "%.2f" % e["t_excess"] if e.get("t_excess") is not None else "—",
                   "%.2f" % e["t"] if e["t"] is not None else "—"))

    # ---- 净流出侧（反向用法：大跌赎回之后能不能抄） ----
    of = M.get("outflow") or {}
    of_rows = ""
    for thr, lab in (("-100", "&lt; −100 亿"), ("-200", "&lt; −200 亿")):
        e = of.get(thr)
        if not e:
            continue
        of_rows += ("<tr><td>%s</td><td class=\"num\">%d</td><td class=\"num\">%d</td>"
                    "<td class=\"num %s\">%s%%</td><td class=\"num\">%s%%</td>"
                    "<td class=\"num %s\"><b>%s</b></td><td class=\"num\">%s</td></tr>"
                    % (lab, e["n"], e["clusters"], cls(e["mean"]), fmt(e["mean"], 2, True),
                       fmt(e["base"], 2, True), cls(e["excess"]), fmt(e["excess"], 2, True),
                       "%.2f" % e["t_excess"] if e.get("t_excess") is not None else "—"))

    # ---- 逐年 β 表 ----
    beta_rows = ""
    for b in (M.get("beta_year") or []):
        beta_rows += ("<tr><td>%s</td><td class=\"num %s\"><b>%+.1f</b></td>"
                      "<td class=\"num\">%+.3f</td><td class=\"num\">%d</td></tr>"
                      % (b["year"], cls(b["beta_same_day"]), b["beta_same_day"],
                         b["corr_same_day"], b["n"]))

    # ---- 游程表 ----
    run_rows = ""
    for r in M["runs_top"]:
        run_rows += ("<tr><td>%s ~ %s</td><td class=\"num\">%d</td>"
                     "<td class=\"num up\">%s</td></tr>" % (r["start"], r["end"], r["days"], fmt(r["sum"], 0)))

    # ---- 明细表 ----
    qmap = {q["code"]: q for q in quotes}
    fund_rows = ""
    for f in sorted(fund_list, key=lambda x: -x["cum_ytd"]):
        q = qmap.get(f["code"])
        fund_rows += (
            '<tr><td class="code">%s</td><td>%s</td><td class="cat">%s</td>'
            '<td class="num">%s</td><td class="num %s">%s</td>'
            '<td class="num">%s</td><td class="num %s">%s</td>'
            '<td class="num %s">%s</td></tr>'
            % (f["code"], f["name"], f.get("cat", ""),
               "%.3f" % q["price"] if q else "—",
               cls(q["pct"]) if q else "flat",
               ("%+.2f%%" % q["pct"]) if q else "—",
               "%.1f" % q["amount_yi"] if q else "—",
               cls(f["cum20"]), fmt(f["cum20"], 0, True),
               cls(f["cum_ytd"]), fmt(f["cum_ytd"], 0, True)))

    # ---- 阈值时效性表 ----
    thresh_rows = ""
    for r in (M.get("thresh_diag") or []):
        mult = r.get("mult")
        bad = mult is not None and mult < 2.0
        thresh_rows += (
            "<tr><td>%s</td><td class=\"num\">%d</td><td class=\"num\">%s</td>"
            "<td class=\"num%s\">%s</td><td class=\"num\">%.1f%%</td><td class=\"num\">%s</td></tr>"
            % (r["year"], r["n"], fmt(r["abs_median"], 1),
               " warncell" if bad else "", ("%.2f×" % mult) if mult else "—",
               r["trig"], fmt(r["q90"], 1)))

    # ---- 阈值敏感性矩阵（grid 版，单元格独立成块） ----
    ts = M.get("thresh_sens") or {}
    _ths = ts.get("thresholds", [])
    sens_rows = ""
    for r in ts.get("rows", []):
        cells = ""
        for c in r["cells"]:
            v = c["excess"]
            if v is None:
                cells += ('<div class="sg-c" style="background:#fafbfc;color:#b0b8c4">'
                          '—<span>%d</span></div>' % c["n"])
                continue
            bg = ("background:#f7e0dc;color:#8c2b20;font-weight:600" if v >= 0.8 else
                  "background:#dcefe4;color:#16603a;font-weight:600" if v <= -0.8 else
                  "background:#f2f4f7;color:#7b8798")
            cells += ('<div class="sg-c" style="%s">%+.2f<span>%d</span></div>' % (bg, v, c["n"]))
        sens_rows += '<div class="sg-y">%s</div>%s' % (r["year"], cells)
    sens_head = "".join('<div class="sg-h">&gt;%d 亿</div>' % t for t in _ths)
    sens_cols = "70px repeat(%d,1fr)" % max(len(_ths), 1)
    roll_rows = "".join(
        '<tr><td>%s</td><td class="num">%d</td><td class="num %s"><b>%+.2fpp</b></td></tr>'
        % (r["year"], r["n"], cls(r["excess"]), r["excess"]) for r in ts.get("rolling", []))

    # ---- 成交额诊断表 ----
    amt_rows = ""
    for r in ((M.get("amt_diag") or {}).get("byyear") or []):
        cs = r["corr_signed"]
        amt_rows += (
            "<tr><td>%s</td><td class=\"num\">%d</td><td class=\"num%s\">%+.3f</td>"
            "<td class=\"num\">%+.3f</td><td class=\"num\">%d</td><td class=\"num\">%.0f%%</td></tr>"
            % (r["year"], r["n"], " warncell" if cs < 0 else "", cs,
               r["corr_abs"], r["hi_n"], r["hi_up"]))
    ad_last = (M.get("amt_diag") or {}).get("byyear") or []
    ad26 = next((r for r in ad_last if r["year"] == "2026"), None)
    proxy_txt = " / ".join("%d 亿 → %.0f%%" % (p["amt"], p["prec"])
                           for p in ((M.get("amt_diag") or {}).get("proxy") or []))

    # ---- 状态样式 ----
    light_map = {"green": ("#1e8449", "可用"), "amber": ("#a56a00", "观察"), "red": ("#c0392b", "失效")}
    lc, llab = light_map[h["light"]]

    # 数据新鲜度：份额 T+1 披露，成交额/行情当日可得，日期差属正常节奏而非缺失
    dh = M.get("data_health", {})
    alert = ""
    if dh.get("share_last") and dh.get("amount_last") and dh["share_last"] < dh["amount_last"]:
        alert = ('<div class="alert">'
                 '<b>净流入比行情慢一拍，这是披露节奏，不是数据缺失。</b>'
                 '交易所份额 T+1 才披露——当前净流入截至 <b>%s</b>，成交额与行情已到 <b>%s</b>。'
                 '次日刷新会自动补齐。'
                 '</div>' % (dh["share_last"], dh["amount_last"]))
    elif not dh.get("share_last"):
        alert = ('<div class="alert"><b>份额库为空。</b>'
                 '先跑 <code>feed/shares.py --backfill</code> 建立历史，再日更。</div>')

    # ---- 首屏结论带：一句话讲清「今天这个信号能不能用」 ----
    t26 = next((r for r in (M.get("thresh_diag") or []) if r["year"] == "2026"), None)
    a26 = ad26
    if h["light"] == "red":
        head = "现在不能跟着买"
    elif h["light"] == "amber":
        head = "信号偏弱，只能小仓试探"
    else:
        head = "信号可用，可以跟"
    v1 = ("β<sub>120</sub> = %s　%s" % (h["beta120"], "跌了才买" if (h["beta120"] or 0) < 0 else "涨了才买"))
    v2 = ("100 亿 = %.2f× 中位　触发 %.1f%%" % (t26["mult"], t26["trig"])) if t26 and t26.get("mult") else "—"
    v3 = ("corr(额, 净流入) = %+.2f" % a26["corr_signed"]) if a26 else "—"
    verdict = (
        '<div class="verdict">'
        '<div class="vd-h"><span class="vd-tag" style="background:%s">%s</span>'
        '<b>%s</b><span class="vd-s">钱在进（近 20 日 %s 亿），但买盘性质已变，事件后 5 日超额只有 %+.2fpp</span></div>'
        '<div class="vd-g">'
        '<div><div class="vk">钱的性质</div><div class="vv">%s</div><div class="vn">净流入对当日涨跌的 120 日回归斜率，负值=接刀</div></div>'
        '<div><div class="vk">阈值还管用吗</div><div class="vv">%s</div><div class="vn">__THRESH__ 亿相对当期中位数的倍数，掉到 2 倍以下即已退化</div></div>'
        '<div><div class="vk">成交额能指方向吗</div><div class="vv">%s</div><div class="vn">2026 年成交额越大越可能是赎回，方向不可用</div></div>'
        '</div></div>'
        % (lc, llab, head, fmt(cur["last20"], 0, True), h["excess5_120d"] or 0, v1, v2, v3))

    # ---- 文案细节：避免「已连续 0 个交易日净流出」这类语病/硬编码 ----
    sn, sp, lnf = cur["streak_neg"], cur["streak_pos"], cur["last_nf"]
    if sn > 0:
        streak_txt = "已连续 %d 个交易日净流出" % sn
    elif sp > 0:
        streak_txt = "已连续 %d 个交易日净流入" % sp
    else:
        streak_txt = "上一交易日单日%s" % ("净流入" if lnf >= 0 else "净流出")

    # 20 日窗口里到底含几天那段连续流入（原写死「17 天」会随窗口滚动而错）
    _d20 = S["dates"][-20] if len(S["dates"]) >= 20 else S["dates"][0]
    _run = (M.get("narrative") or {}).get("run2026")
    tail_txt = "近 20 个交易日合计"
    if _run and _run["end"] >= _d20:
        _ov = sum(1 for d in S["dates"][-20:] if _run["start"] <= d <= _run["end"])
        if _ov:
            tail_txt = "含 %d 天连续流入尾巴" % _ov

    # 行情时点：早上跑拿到的是上一交易日收盘，必须在页面上标出来
    _qt = next((q.get("time") for q in (P.get("quotes") or []) if q.get("time")), "") or ""
    if len(_qt) >= 12:
        q_date = "%s-%s-%s" % (_qt[:4], _qt[4:6], _qt[6:8])
        q_hm = "%s:%s" % (_qt[8:10], _qt[10:12])
        q_txt = "%s %s" % (q_date, q_hm)
    else:
        q_date, q_txt = "—", "—"

    html = TEMPLATE
    html = html.replace("__VERDICT__", verdict)
    html = html.replace("__ALERT__", alert)
    html = html.replace("__TITLE_DATE__", cur["last_date"])
    html = html.replace("__FETCHED__", M.get("built_at", ""))
    html = html.replace("__ASOF__", M["asof"])
    html = html.replace("__NDAYS__", str(M["n_days"]))
    html = html.replace("__LIGHT__", h["light"])
    html = html.replace("__LIGHTC__", lc)
    html = html.replace("__LIGHTLAB__", llab)
    html = html.replace("__SCORE__", "%+d" % h["score"])
    html = html.replace("__NF_LAST__", fmt(cur["last_nf"], 1, True))
    html = html.replace("__NF_LAST_C__", cls(cur["last_nf"]))
    html = html.replace("__NF5__", fmt(cur["last5"], 0, True))
    html = html.replace("__NF5_C__", cls(cur["last5"]))
    html = html.replace("__NF20__", fmt(cur["last20"], 0, True))
    html = html.replace("__NF20_C__", cls(cur["last20"]))
    html = html.replace("__BETA__", "%s" % h["beta120"])
    html = html.replace("__EX5__", "%+.2f" % (h["excess5_120d"] or 0))
    html = html.replace("__IDXLIVE__", "%.2f" % px_last if px_last else "—")
    html = html.replace("__IDXLIVE_PCT__", "%+.2f%%" % live_pct if live_pct is not None else "—")
    html = html.replace("__IDXLIVE_C__", cls(live_pct or 0))
    _d = str(im.get("date") or "")
    if len(_d) == 8:
        _d = "%s-%s-%s" % (_d[:4], _d[4:6], _d[6:])
    html = html.replace("__IMDATE__", _d or "—")
    html = html.replace("__STREAK__", "%d" % cur["streak_neg"])
    html = html.replace("__STREAK_TXT__", streak_txt)
    html = html.replace("__TAIL_TXT__", tail_txt)
    html = html.replace("__QTIME__", q_txt)
    html = html.replace("__NCODES__", str(M["scope"]["n_codes"]))
    html = html.replace("__THRESH__", "%g" % M["thresh"])
    html = html.replace("__TABDAYS__", str(len(recent)))
    html = html.replace("__START__", M["scope"]["start"])
    _empty = M["broad"].get("cats_empty") or []
    html = html.replace("__EMPTYTXT__", (
        "深市分类（%s）因交易所不提供历史份额，暂缺——深市是逐日累积的，攒够天数后会自动出现。"
        % " / ".join(_empty)) if _empty else "九类宽基均已覆盖沪深两市。")
    html = html.replace("__BROAD_TABLE__", broad_table)
    html = html.replace("__EV_ROWS__", "".join(ev_rows))
    html = html.replace("__OF_ROWS__", of_rows)
    html = html.replace("__BETA_ROWS__", beta_rows)
    html = html.replace("__THRESH_ROWS__", thresh_rows)
    html = html.replace("__SENS_HEAD__", sens_head)
    html = html.replace("__SENS_COLS__", sens_cols)
    html = html.replace("__SENS_ROWS__", sens_rows)
    html = html.replace("__ROLL_ROWS__", roll_rows)
    html = html.replace("__AMT_ROWS__", amt_rows)
    html = html.replace("__PROXY_TEXT__", proxy_txt or "—")
    html = html.replace("__RUN_ROWS__", run_rows)
    html = html.replace("__FUND_ROWS__", fund_rows)
    html = html.replace("__HEALTH_ITEMS__", "".join(
        '<div class="hitem"><div class="hk">%s</div><div class="hv %s">%s</div>'
        '<div class="hn">%s</div></div>'
        % (i["k"], "up" if i["s"] > 0 else ("down" if i["s"] < 0 else "flat"), i["v"], i["note"])
        for i in h["items"]))
    narr = M.get("narrative") or {}
    r26, rl = narr.get("run2026"), narr.get("longest")

    def _pct(v):
        return ("涨了 %.2f%%" % v) if (v or 0) >= 0 else ("跌了 %.2f%%" % abs(v))

    html = html.replace("__R26_DATES__", "%s 至 %s" % (r26["start"][5:], r26["end"][5:]) if r26 else "—")
    html = html.replace("__R26_DAYS__", str(r26["days"]) if r26 else "—")
    html = html.replace("__R26_SUM__", fmt(r26["sum"], 0) if r26 else "—")
    html = html.replace("__R26_PCT__", _pct(r26.get("idx_pct")) if r26 else "—")
    html = html.replace("__RL_DATES__", "%s 至 %s" % (rl["start"], rl["end"]) if rl else "—")
    html = html.replace("__RL_DAYS__", str(rl["days"]) if rl else "—")
    html = html.replace("__RL_SUM__", fmt(rl["sum"], 0) if rl else "—")
    html = html.replace("__RL_PCT__", _pct(rl.get("idx_pct")) if rl else "—")
    html = html.replace("__CORR24__", "%+.3f" % narr["corr24"] if narr.get("corr24") is not None else "—")
    html = html.replace("__CORR26__", "%+.3f" % narr["corr26"] if narr.get("corr26") is not None else "—")
    html = html.replace("__PREVCLOSE__", "%.2f" % cur["idx_last"])
    html = html.replace("__AMT_TODAY__", fmt(minute["amt"], 0))
    html = html.replace("__AMT_MA20__", fmt(minute["ma20"], 0))
    html = html.replace("__AMT_RATIO__", "%.2f" % (minute["ratio"] or 0))
    html = html.replace("__AMT_RATIO_C__", "up" if (minute["ratio"] or 0) >= 1 else "flat")
    html = html.replace("__DATA__", json.dumps(chart, ensure_ascii=False, separators=(",", ":")))

    os.makedirs(REPORTS, exist_ok=True)
    p = os.path.join(REPORTS, "ETF国家队资金监测面板.html")
    open(p, "w", encoding="utf-8").write(html)
    print("[build] %s  %.0f KB" % (p, os.path.getsize(p) / 1024))
    return p


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>重点 ETF 资金监测面板</title>
<style>
:root{
  --ink:#111a26;--ink2:#3f5066;--ink3:#7b8798;--line:#e3e8ef;--line2:#eef1f6;
  --red:#c0392b;--redbg:#fcf1ef;--green:#1e8449;--greenbg:#f0f7f3;
  --amber:#a56a00;--amberbg:#fdf8ec;--bg:#f4f6f9;--card:#fff;
  --mono:"SF Mono",ui-monospace,Menlo,Consolas,monospace;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-size:14px;line-height:1.7;
 font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
 -webkit-font-smoothing:antialiased}
.wrap{max-width:1160px;margin:0 auto;padding:0 20px 70px}
/* 顶栏 */
.topbar{background:#fff;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:30}
.topbar-in{max-width:1160px;margin:0 auto;padding:11px 20px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.brand{font-size:16px;font-weight:700;letter-spacing:-.2px}
.brand span{color:var(--ink3);font-weight:500;font-size:12.5px;margin-left:8px}
.nav{margin-left:auto;display:flex;gap:14px;font-size:12.5px}
.nav a{color:var(--ink2);text-decoration:none;padding:3px 0;border-bottom:1px solid transparent}
.nav a:hover{color:var(--ink);border-bottom-color:var(--ink)}
/* 概览 */
.hero{padding:24px 0 4px}
.hero h1{margin:0 0 6px;font-size:25px;font-weight:700;letter-spacing:-.5px}
.hero .sub{color:var(--ink3);font-size:12.5px}
.alert{margin:14px 0 0;padding:11px 14px;border-radius:8px;background:var(--amberbg);
 border:1px solid #f0dfb8;color:#7a5200;font-size:12.8px;line-height:1.65}
.alert b{color:#5c3d00}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:16px 0 6px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:13px 15px}
.kpi .k{font-size:12px;color:var(--ink3);margin-bottom:5px;letter-spacing:.2px}
.kpi .v{font-size:24px;font-weight:700;letter-spacing:-.6px;font-variant-numeric:tabular-nums}
.kpi .v small{font-size:12.5px;font-weight:500;margin-left:3px;color:var(--ink3)}
.kpi .n{font-size:11.5px;color:var(--ink3);margin-top:3px}
.kpi .light{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:1px}
/* 首屏结论带 */
.verdict{margin:14px 0 4px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.vd-h{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap;padding-bottom:11px;border-bottom:1px solid var(--line2)}
.vd-tag{font-size:11.5px;font-weight:700;color:#fff;padding:2px 7px;border-radius:4px;letter-spacing:.3px}
.vd-h b{font-size:16.5px;letter-spacing:-.3px}
.vd-s{font-size:12.2px;color:var(--ink3);line-height:1.6}
.vd-g{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:11px}
.vk{font-size:11.5px;color:var(--ink3)}
.vv{font-size:14px;font-weight:650;margin:2px 0 1px;font-variant-numeric:tabular-nums;letter-spacing:-.2px}
.vn{font-size:11px;color:var(--ink3);line-height:1.5}
.warncell{color:#a56a00;font-weight:700}
.sensgrid{display:grid;gap:5px;margin:8px 0 2px;align-items:center}
.sg-h{font-size:11px;color:var(--ink3);text-align:right;padding:0 7px 2px 0}
.sg-y{font-size:12.5px;font-weight:600;color:var(--ink2)}
.sg-c{border-radius:5px;padding:9px 9px;text-align:right;font-size:13px;
 font-variant-numeric:tabular-nums;letter-spacing:-.2px}
.sg-c span{font-size:10.5px;opacity:.55;margin-left:5px;font-weight:400}
/* 区块 */
.sec{margin-top:28px}
.sec-h{display:flex;align-items:baseline;gap:10px;margin:0 0 4px;padding-bottom:9px;border-bottom:1px solid var(--line)}
.sec-h h2{margin:0;font-size:17px;font-weight:700;letter-spacing:-.2px}
.sec-h .no{font-family:var(--mono);font-size:12px;color:var(--ink3)}
.sec-h .hint{font-size:12px;color:var(--ink3);margin-left:auto}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px 8px;margin-top:12px}
.card h3{margin:0 0 2px;font-size:13.5px;font-weight:600}
.card .cap{font-size:11.8px;color:var(--ink3);margin:2px 0 8px;line-height:1.6}
.chart{width:100%;height:330px}
.chart.tall{height:380px}
/* 表 */
table{border-collapse:collapse;width:100%;font-size:12.3px;font-variant-numeric:tabular-nums}
th,td{padding:6px 8px;border-bottom:1px solid var(--line2);text-align:left;white-space:nowrap}
thead th{font-weight:600;color:var(--ink2);background:#fafbfc;border-bottom:1px solid var(--line);
 font-size:11.8px;position:sticky;top:0}
td.num,th.num{text-align:right}
.matrix td{padding:4px 5px;font-size:11.3px;text-align:right;border:none}
.matrix th{font-size:11px;font-weight:600;padding:4px 5px;border:none;background:none;color:var(--ink3)}
.matrix .rowh{text-align:left;font-size:11.6px;color:var(--ink2);font-weight:600;position:static}
.matrix .tot{font-weight:700;border-left:1px solid var(--line)}
.tscroll{max-height:340px;overflow:auto;border:1px solid var(--line2);border-radius:8px}
.tscroll thead th{z-index:2}
.up{color:var(--red)}.down{color:var(--green)}.flat{color:var(--ink3)}
.code{font-family:var(--mono);font-size:11.6px;color:var(--ink3)}
/* 体检 */
.health{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-top:12px}
.hgrid{display:grid;grid-template-columns:1.05fr 2fr;gap:18px;align-items:center}
.lightbox{border-right:1px solid var(--line2);padding-right:18px}
.lightbig{display:flex;align-items:center;gap:10px}
.dotbig{width:14px;height:14px;border-radius:50%;box-shadow:0 0 0 5px rgba(0,0,0,.04)}
.lightbig .t{font-size:21px;font-weight:700;letter-spacing:-.4px}
.lightbig .s{font-size:12px;color:var(--ink3);font-family:var(--mono)}
.hitems{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.hitem{border-left:2px solid var(--line);padding-left:10px}
.hitem .hk{font-size:11.5px;color:var(--ink3)}
.hitem .hv{font-size:17px;font-weight:700;font-variant-numeric:tabular-nums;letter-spacing:-.3px}
.hitem .hn{font-size:11px;color:var(--ink3);line-height:1.5;margin-top:2px}
.note{font-size:12.2px;color:var(--ink2);margin:12px 0 0;padding:11px 13px;background:#fafbfc;
 border-left:2px solid var(--ink3);border-radius:0 6px 6px 0}
footer{margin-top:34px;padding-top:14px;border-top:1px solid var(--line);font-size:11.5px;color:var(--ink3);line-height:1.8}
@media (max-width:860px){
 .kpis{grid-template-columns:repeat(2,1fr)}
 .hgrid{grid-template-columns:1fr}
 .lightbox{border-right:none;border-bottom:1px solid var(--line2);padding:0 0 14px}
 .hitems{grid-template-columns:1fr}
 .nav{display:none}
}
</style>
<script src="echarts.min.js"></script>
<script src="chart-boot.js"></script>
</head>
<body>

<div class="topbar"><div class="topbar-in">
  <div class="brand">宽基 ETF 资金监测面板<span>沪市 __NCODES__ 只 · 9 类宽基 · 两融</span></div>
  <nav class="nav">
    <a href="#s0">⓿ 今日盘中</a><a href="#s1">① 日度资金</a><a href="#s2">② 分类结构</a><a href="#s3">③ 放量信号</a>
    <a href="#s4">④ 两融</a><a href="#s5">⑤ 单只明细</a><a href="#s6">⑥ 信号体检</a>
  </nav>
</div></div>

<div class="wrap">
  <div class="hero">
    <h1>宽基 ETF 资金监测面板</h1>
    <div class="sub">净流入数据截至 <b>__TITLE_DATE__</b>（自建申赎口径：份额变动 × 单位净值，共 __NDAYS__ 个交易日）　·　
      上证 <b class="__IDXLIVE_C__">__IDXLIVE__</b>（<span class="__IDXLIVE_C__">__IDXLIVE_PCT__</span>，__IMDATE__）　·　构建时间 __FETCHED__</div>
    __ALERT__
    <div class="kpis">
      <div class="kpi">
        <div class="k">最新单日净流入（沪市宽基合计）</div>
        <div class="v __NF_LAST_C__">__NF_LAST__<small>亿</small></div>
        <div class="n">__TITLE_DATE__　份额×净值</div>
      </div>
      <div class="kpi">
        <div class="k">近 5 日累计</div>
        <div class="v __NF5_C__">__NF5__<small>亿</small></div>
        <div class="n">__STREAK_TXT__</div>
      </div>
      <div class="kpi">
        <div class="k">近 20 日累计</div>
        <div class="v __NF20_C__">__NF20__<small>亿</small></div>
        <div class="n">__TAIL_TXT__</div>
      </div>
      <div class="kpi">
        <div class="k">信号状态</div>
        <div class="v" style="color:__LIGHTC__"><span class="light" style="background:__LIGHTC__"></span>__LIGHTLAB__</div>
        <div class="n">β<sub>120</sub>=__BETA__　近 120 日 5 日超额 __EX5__pp</div>
      </div>
    </div>
    __VERDICT__
  </div>

  <section class="sec" id="s0">
    <div class="sec-h"><span class="no">00</span><h2>今日盘中</h2>
      <span class="hint">实时抓取　·　__IMDATE__ 收盘</span></div>
    <div class="card">
      <h3>上证综指分时（虚线=昨收 __PREVCLOSE__，收盘 __IDXLIVE__）</h3>
      <div class="cap">盘中看两件事：指数在昨收上下的位置，以及沪市宽基 ETF 的成交额有没有异常放大。放量而指数不涨，就是有人在承接，方向要等净流入数据确认。</div>
      <div id="cMinute" class="chart"></div>
    </div>
    <div class="card" style="padding-bottom:14px">
      <div style="display:flex;gap:32px;flex-wrap:wrap;align-items:baseline">
        <div><div class="k" style="font-size:12px;color:var(--ink3)">今日宽基 ETF 合计成交额</div>
          <div style="font-size:22px;font-weight:700;letter-spacing:-.5px">__AMT_TODAY__<small style="font-size:12px;color:var(--ink3);margin-left:3px">亿</small></div></div>
        <div><div class="k" style="font-size:12px;color:var(--ink3)">20 日均值</div>
          <div style="font-size:22px;font-weight:700;letter-spacing:-.5px;color:var(--ink2)">__AMT_MA20__<small style="font-size:12px;color:var(--ink3);margin-left:3px">亿</small></div></div>
        <div><div class="k" style="font-size:12px;color:var(--ink3)">放量倍数</div>
          <div style="font-size:22px;font-weight:700;letter-spacing:-.5px" class="__AMT_RATIO_C__">__AMT_RATIO__<small style="font-size:12px;color:var(--ink3);margin-left:3px">倍</small></div></div>
        <div style="flex:1;min-width:220px;font-size:12px;color:var(--ink3);line-height:1.6">
          成交额只说明有人在交易，不区分申购与赎回。倍数 &gt;1.4 倍且指数下跌，是典型的承接形态，但要等 T 日净流入披露才能定性。</div>
      </div>
    </div>
  </section>

  <section class="sec" id="s1">
    <div class="sec-h"><span class="no">01</span><h2>日度资金全景</h2>
      <span class="hint">近 180 个交易日　·　沪市宽基 ETF 申赎净流入</span></div>
    <div class="card">
      <h3>净流入与上证综指</h3>
      <div class="cap">柱=沪市宽基合计净流入（红=净申购，绿=净赎回），线=上证综指收盘（右轴）。柱高与指数背离的区间，就是买盘没能推动价格的地方。</div>
      <div id="cFlow" class="chart tall"></div>
    </div>
  </section>

  <section class="sec" id="s2">
    <div class="sec-h"><span class="no">02</span><h2>分类结构</h2>
      <span class="hint">沪市宽基 ETF 按跟踪指数归集　·　全样本</span></div>
    <div class="card">
      <h3>近 60 日各类宽基净流入</h3>
      <div class="cap">各宽基分类的日度净流入堆叠（红正绿负），近 60 个交易日。看钱是集中在沪深300，还是被分散到主题。__EMPTYTXT__</div>
      <div id="cBroad" class="chart tall"></div>
    </div>
    <div class="card">
      <h3>分类累计净流入（2024 年初起）</h3>
      <div class="cap">各分类自 2024 年初的累计。斜率变化比单日数值更能说明态度转变；单类量级差异大，故不叠加合计线。</div>
      <div id="cBroadCum" class="chart"></div>
    </div>
    <div class="card">
      <h3>最近一个月 · 各分类日度净流入（亿元）</h3>
      <div class="cap">颜色深浅按当行最大绝对值，便于看谁在同一个方向上连续发力。</div>
      <div style="overflow-x:auto;padding-bottom:6px">__BROAD_TABLE__</div>
    </div>
  </section>

  <section class="sec" id="s3">
    <div class="sec-h"><span class="no">03</span><h2>放量信号</h2>
      <span class="hint">成交额只定事件强度，不定方向</span></div>
    <div class="card">
      <h3>宽基 ETF 日度成交额</h3>
      <div class="cap">柱=成交额，虚线=20 日均值，橙柱=当日净流入 &gt;__THRESH__ 亿的放量日。<b>橙柱只标「那天是净申购」，灰柱里同样藏着巨额赎回</b>——同一个放量形态，方向可以完全相反，所以要靠 T 日盘后的份额变化定性。</div>
      <div id="cAmt" class="chart tall"></div>
    </div>
    <div class="card">
      <h3>成交额到底能预测什么：强度可以，方向不行</h3>
      <div class="cap">左柱=成交额与净流入的相关（方向），右柱=成交额与 |净流入| 的相关（强度）。<b>2026 年两根柱劈叉</b>：强度相关冲到年内最高，方向相关转负——成交额越准地告诉你「今天有大事」，就越不能告诉你「是买还是卖」。</div>
      <div id="cAmtCorr" class="chart"></div>
    </div>
    <div class="card" style="padding-bottom:14px">
      <h3>逐年检验</h3>
      <div class="cap">高量日 = 当年成交额前 10% 的交易日。若成交额能代理方向，高量日里「净流入 &gt;__THRESH__ 亿」的比例应显著高于基准率（全样本 8.2%）。</div>
      <div class="tscroll" style="max-height:none">
        <table><thead><tr><th>年份</th><th class="num">样本天数</th><th class="num">corr(额, 净流入)</th>
          <th class="num">corr(额, |净流入|)</th><th class="num">高量日数</th><th class="num">高量日中净流入&gt;100亿</th></tr></thead>
          <tbody>__AMT_ROWS__</tbody></table>
      </div>
      <div class="note" style="margin-top:12px">把成交额当「今天有大事」的报警器是有效的；当「今天是买是卖」的判据则是错的。
        用成交额阈值去代理 100 亿事件，精确率只有 __PROXY_TEXT__——
        每判 10 次有 5~7 次是误报。这是盘中看不到申赎数据时的结构性缺陷，不是参数没调好。</div>
    </div>
  </section>

  <section class="sec" id="s4">
    <div class="sec-h"><span class="no">04</span><h2>ETF 两融</h2>
      <span class="hint">沪深两市融资余额合计　·　交易所 T+1 披露</span></div>
    <div class="card">
      <h3>融资余额（沪深合计）</h3>
      <div class="cap">杠杆资金是另一个买盘来源。与 ETF 净流入同向时，说明是趋势资金；反向时，多半是对冲。</div>
      <div id="cMarginBal" class="chart"></div>
    </div>
    <div class="card">
      <h3>融资净买入（余额日差，亿元）</h3>
      <div class="cap">单日净买入的正负切换，通常比余额变化早 1–3 个交易日。</div>
      <div id="cMarginFlow" class="chart"></div>
    </div>
  </section>

  <section class="sec" id="s5">
    <div class="sec-h"><span class="no">05</span><h2>单只明细</h2>
      <span class="hint">行情时点 __QTIME__　·　累计列为年初至今</span></div>
    <div class="card">
      <h3>沪市宽基 ETF</h3>
      <div class="cap">按年初以来累计净流入降序。成交额单位亿元；累计列红=净申购、绿=净赎回。深市份额交易所不提供历史回溯，故本表仅含沪市标的。</div>
      <div class="tscroll">
        <table><thead><tr><th>代码</th><th>名称</th><th>分类</th><th class="num">最新价</th><th class="num">当日涨跌</th>
          <th class="num">成交额</th><th class="num">20日累计</th><th class="num">年初以来</th></tr></thead>
          <tbody>__FUND_ROWS__</tbody></table>
      </div>
    </div>
    <div class="card">
      <h3>累计净流入路径（2026 年初至今）</h3>
      <div class="cap">年初以来累计最大的 5 只。分叉出现在哪一天，就是这批钱的配置重心搬家的时候（合计见 01 节）。</div>
      <div id="cCum" class="chart"></div>
    </div>
  </section>

  <section class="sec" id="s6">
    <div class="sec-h"><span class="no">06</span><h2>信号体检</h2>
      <span class="hint">判断「这个信号今天还能不能用」——面板的核心增量</span></div>

    <div class="health">
      <div class="hgrid">
        <div class="lightbox">
          <div class="lightbig">
            <span class="dotbig" style="background:__LIGHTC__"></span>
            <div><div class="t" style="color:__LIGHTC__">__LIGHTLAB__</div>
              <div class="s">评分 __SCORE__ / ±4</div></div>
          </div>
          <div class="cap" style="margin:8px 0 0">三分项加权：性质 ±2、超额 ±1、买盘 ±1。低于 0 即视为不可用。</div>
        </div>
        <div class="hitems">__HEALTH_ITEMS__</div>
      </div>
      <div class="note">
        <b>怎么读这个灯。</b>只看「净流入多不多」会一直误判——2026 年 __R26_DATES__ 连续 __R26_DAYS__ 个交易日、
        __R26_SUM__ 亿，是年内最长的一轮，指数反而__R26_PCT__。样本内最长的是 __RL_DATES__，__RL_DAYS__ 天
        __RL_SUM__ 亿，那轮指数__RL_PCT__。灯变红的原因不是钱少，是
        <b>β<sub>120</sub> 转负</b>：净流入与当日涨跌的相关性从 2024 年的 __CORR24__ 变成 __CORR26__，
        同一笔钱从「涨了才买」变成「跌了才买」，性质从助推变成了接刀。
      </div>
    </div>

    <div class="card">
      <h3>逐年超额衰减</h3>
      <div class="cap">事件 = 单日净流入 &gt;__THRESH__ 亿；T+1 开盘买入，持有 5 / 20 日；超额 = 事件均值 − 同年样本均值。
        红柱为 5 日、蓝柱为 20 日。<b>2026 年 5 日超额已塌到 +0.15pp</b>（2024 / 2025 为 +1.58 / +1.76）；
        20 日那根 +2.22 偏高，是因为 2026 年 28 个事件里有 20 个挤在 7 月和 10–11 月两段申购行情里，
        持有期互相重叠、独立簇只有 6 个，不能当独立证据。</div>
      <div id="cYear" class="chart"></div>
    </div>

    <div class="card">
      <h3>__THRESH__ 亿这个阈值还管用吗</h3>
      <div class="cap">净流入的绝对波动在放大，固定阈值会自己「变松」。用 <b>阈值 ÷ 当年 |净流入| 中位数</b> 衡量它到底还算不算极端事件：倍数越高越严格，掉到 2 倍以下就已经退化成一条普通分位线。</div>
      <div class="tscroll" style="max-height:none">
        <table><thead><tr><th>年份</th><th class="num">样本天数</th><th class="num">|净流入| 中位（亿）</th>
          <th class="num">__THRESH__ 亿 ÷ 中位</th><th class="num">触发频率</th><th class="num">当年 90 分位（亿）</th></tr></thead>
          <tbody>__THRESH_ROWS__</tbody></table>
      </div>
      <div class="note" style="margin-top:12px">2024 年 100 亿相当于中位数的 3 倍多，一年只触发 9.5%；到 2026 年只剩 1.5 倍，触发频率升到 13.5%。
        换句话说<b>同一个数字，考的是完全不同的难度</b>——不能拿 2024 年的阈值去衡量 2026 年的钱。</div>
    </div>

    <div class="card">
      <h3>换阈值后结论会不会变（敏感性检验）</h3>
      <div class="cap">这是判断「信号失效」是否成立的关键一步。如果只有 100 亿失效、把阈值提到 250 亿就恢复，那失效是选阈值选出来的假象；如果各档都失效，才是结构性的。单元格=事件后 5 日超额（pp），右下角小字为事件数。</div>
      <div class="sensgrid" style="grid-template-columns:__SENS_COLS__">
        <div class="sg-h"></div>__SENS_HEAD____SENS_ROWS__
      </div>
      <div class="cap" style="margin:11px 0 5px"><b>再加一档实盘口径</b>：滚动 250 个交易日的 90 分位阈值——事前不知道当年分布，这是唯一能真正用于交易的做法。</div>
      <table><thead><tr><th>年份</th><th class="num">触发天数</th><th class="num">事件后 5 日超额</th></tr></thead>
        <tbody>__ROLL_ROWS__</tbody></table>
      <div class="note" style="margin-top:12px">关键不在数值大小，<b>在形状</b>：如果只是阈值定低了，提高阈值应该单调改善。
        2024/2025 确实如此（100→150 亿反而更高）；<b>2026 年是 0.15 → 0.57 → 0.12 → −0.06，先升后降、250 亿直接转负</b>，
        提高阈值救不回来。加上滚动分位口径的 +0.13pp，结论一致：失效是买盘行为变了，不是参数没调好。</div>
    </div>

    <div class="card">
      <h3>反向检验：大额赎回之后能不能抄</h3>
      <div class="cap">上面测的是「跟着买」，这里测反过来的用法——净流出超过阈值之后 20 日的表现，看跌下来是不是机会。
        「基准」是同期全样本 20 日均值，超额 = 事件均值 − 基准；超额为负就是<b>跑输随机一天买进去</b>。</div>
      <div class="tscroll" style="max-height:none">
        <table><thead><tr><th>触发条件</th><th class="num">事件数</th><th class="num">独立簇</th>
          <th class="num">20 日均值</th><th class="num">基准</th><th class="num">超额</th><th class="num">t(超额)</th></tr></thead>
          <tbody>__OF_ROWS__</tbody></table>
      </div>
      <div class="note" style="margin-top:12px">结论是不成立。<b>&lt; −100 亿</b>之后 20 日平均 −0.90%、超额 −1.80pp，
        看着像「赎回之后继续跌」，但 t(超额) 只有 −1.25；<b>&lt; −200 亿</b>那一档 21 个事件只剩 4 个独立簇，
        t 反而回到 +0.36——样本太少，连方向都测不稳。所以这个面板目前<b>正反两个方向都没有统计上站得住的跟单信号</b>，
        这不是数据不够，是 2026 年的买盘本身已经不按这个逻辑走了。</div>
    </div>

    <div class="card">
      <h3>逐年 β：同一笔钱的性质怎么变的</h3>
      <div class="cap">β = 净流入对当日指数涨跌的回归斜率（亿元 / 每 1% 涨跌）。<b>正=涨了才买（助推），负=跌了才买（接刀）</b>。这张表是「失效」结论里最硬的一条证据，因为它不依赖阈值、不依赖事件定义。</div>
      <div class="tscroll" style="max-height:none">
        <table><thead><tr><th>年份</th><th class="num">β（同日）</th><th class="num">相关系数</th><th class="num">样本天数</th></tr></thead>
          <tbody>__BETA_ROWS__</tbody></table>
      </div>
      <div class="note" style="margin-top:12px">2024 年 β=+16.4，钱是<b>顺着价格</b>进来的；2026 年 β=−30.1，钱是<b>逆着价格</b>进来的。
        同样是「净流入 100 亿」，2024 年那笔是在追涨，2026 年那笔是在接刀——<b>方向相同的数字，含义完全相反</b>。
        这也解释了为什么超额会衰减：接刀的钱本身不创造上涨，只是承接抛压。</div>
    </div>

    <div class="card">
      <h3>滚动 120 日 β：净流入 ~ 当日涨跌</h3>
      <div class="cap">β&gt;0 表示当日越涨申购越多（顺势助推）；β&lt;0 表示越跌申购越多（逆势接刀）。零轴是分界。纵轴单位：亿元 / 每 1% 指数涨跌。</div>
      <div id="cRoll" class="chart"></div>
    </div>

    <div class="card">
      <h3>事件研究明细</h3>
      <div class="cap">样本 2023-12 至 __ASOF__。簇 = 相隔 20 个交易日内的连续事件合并，避免同一波买盘被算成多个独立样本。
        <b>最后两列是两个不同的 t</b>：t(超额) 检验「跑赢基准」是否显著，t(相对0) 检验「赚不赚钱」是否显著，基准离 0 越远两者差越大。</div>
      <div class="tscroll">
        <table><thead><tr><th>区间</th><th class="num">持有期</th><th class="num">事件数</th><th class="num">独立簇</th>
          <th class="num">事件均值</th><th class="num">基准均值</th><th class="num">超额</th>
          <th class="num">t(超额)</th><th class="num">t(相对0)</th></tr></thead>
          <tbody>__EV_ROWS__</tbody></table>
      </div>
      <div class="note" style="margin-top:12px"><b>这张表最该看的是「独立簇」而不是「事件数」。</b>
        2026 年 28 个事件只落在 6 个簇里，等于只有 6 个独立观测，t 值再怎么算都没有判别力。
        事实上两种口径下 2026 年的 t(超额) 反而是三年里最高的（1.11 / 1.04），而 2024 年只有 0.07 / 0.52——
        <b>如果只看 t 值，会得出「2026 比 2024 更可靠」的相反结论</b>。所以这里不用 t 值判定有效或失效，
        只用点估计落差（+1.58 / +1.76 → +0.15）配合下一张 β 表下结论。</div>
    </div>

    <div class="card">
      <h3>最长连续净流入游程</h3>
      <div class="cap">连续每个交易日净流入为正、且长度 ≥5 天的区间。这是「托底」最直观的形态特征。</div>
      <div class="tscroll" style="max-height:none">
        <table><thead><tr><th>区间</th><th class="num">连续天数</th><th class="num">累计净流入（亿）</th></tr></thead>
          <tbody>__RUN_ROWS__</tbody></table>
      </div>
    </div>

    <footer>
      <b>数据来源（全部自建，不依赖任何第三方看板）</b>　
      份额：上交所 <code>fund_etf_scale_sse</code> 按日回溯 + 深交所快照累积；
      净值：天天基金 <code>f10/lsjz</code> 单位净值；
      成交额：腾讯日线；两融：沪深交易所融资余额；指数：新浪 <code>sh000001</code>。
      构建 __FETCHED__。<br>
      <b>口径</b>　净流入 =（份额_T − 份额_T−1）× 单位净值_T，单位亿元，正数=净申购。
      该口径已与外部 Choice 数据逐日比对：沪市 11 只核心 ETF 相关系数 <b>1.0000</b>、
      平均绝对误差 <b>0.002~0.003 亿元</b>。<br>
      <b>覆盖与限制</b>　沪市 __NCODES__ 只宽基 ETF，__START__ 起完整历史。
      深交所只提供最新份额快照、不提供历史回溯，因此深市标的（创业板指 / 创业板50 / 国证2000）
      从 2026-11-14 起逐日累积，历史段为空——这是数据源的硬限制，不是抓取失败。
      <b>注意：深市是「一天一存」，某个交易日没跑就永久缺那一天，无法回补</b>；沪市可按日回溯补齐，不受影响。<br>
      <b>刷新</b>　
      <code style="font-family:var(--mono);font-size:11px;background:#f4f6f9;padding:1px 5px;border-radius:3px">cd analysis/panel &amp;&amp; ./refresh.sh</code>
     　一条命令完成抓份额→算净流入→重建页面。份额 T+1 披露，故排期为<b>周二至周六上午 8:00</b> 自动运行：
      周二取周一、周三取周二、周六取周五，一周五个交易日刚好一个不缺。asof 恒等于运行日的前一个交易日，属正常节奏。<br>
      <b>免责</b>　本面板为个人研究工具，所有指标由脚本机械计算，不构成投资建议。
    </footer>
  </section>
</div>

<script>
var D = __DATA__;

function fmtAxis(v){ return Math.abs(v)>=100 ? (v/1).toFixed(0) : v; }

/* 0. 今日分时 */
(function(){
  var m = D.minute;
  var el = document.getElementById('cMinute');
  if (!m || !m.t || !m.t.length){ if (el) el.innerHTML = '<div style="padding:40px;text-align:center;color:#7b8798;font-size:12.5px">未取到分时数据</div>'; return; }
  var pct = (m.p[m.p.length-1] / m.prev - 1) * 100;
  var up = pct >= 0;
  CHART('cMinute', {
    color: [up ? '#c0392b' : '#1e8449'],
    grid: { left: 8, right: 14, top: 24, bottom: 30, containLabel: true },
    tooltip: { trigger: 'axis', valueFormatter: function(v){ return v.toFixed(2) + ' 点'; } },
    xAxis: { type: 'category', data: m.t, boundaryGap: false,
      axisLabel: { fontSize: 10.5, hideOverlap: true }, axisTick: { show: false } },
    yAxis: { type: 'value', scale: true, splitLine: { lineStyle: { color: '#eef1f6' } },
      axisLabel: { fontSize: 10.5 } },
    series: [{
      name: '上证综指', type: 'line', data: m.p, showSymbol: false, connectNulls: false,
      lineStyle: { width: 1.6, color: up ? '#c0392b' : '#1e8449' },
      itemStyle: { color: up ? '#c0392b' : '#1e8449' },
      areaStyle: { color: up ? 'rgba(192,57,43,.07)' : 'rgba(30,132,73,.07)' },
      markLine: { silent: true, symbol: 'none',
        lineStyle: { color: '#8a93a3', type: 'dashed', width: 1 },
        label: { formatter: '昨收', position: 'insideEndTop', fontSize: 10.5, color: '#8a93a3' },
        data: [{ yAxis: m.prev }] }
    }]
  });
})();

/* 1. 净流入 + 指数 */
(function(){
  var o = D.flow, pos = [], neg = [];
  o.nf.forEach(function(v){
    pos.push(v >= 0 ? v : null);
    neg.push(v < 0 ? v : null);
  });
  CHART('cFlow', {
    color: ['#c0392b', '#1e8449', '#1f4e79'],
    grid: { left: 8, right: 12, top: 58, bottom: 34, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: function(ps){
        var s = '<b>' + ps[0].axisValue + '</b>';
        ps.forEach(function(p){
          if (p.value == null) return;
          s += '<br>' + p.marker + p.seriesName + '：' +
               (p.seriesType === 'line' ? p.value.toFixed(2) + ' 点' : p.value.toFixed(1) + ' 亿');
        });
        return s;
      } },
    legend: { data: ['净流入(亿)', '上证综指'], top: 4, left: 0, itemWidth: 14, itemHeight: 8, textStyle: { fontSize: 11.5 } },
    xAxis: { type: 'category', data: o.d, axisLabel: { fontSize: 10.5, hideOverlap: true }, axisTick: { show: false } },
    yAxis: [
      { type: 'value', splitLine: { lineStyle: { color: '#eef1f6' } }, axisLabel: { fontSize: 10.5 } },
      { type: 'value', name: '点', scale: true, nameTextStyle: { fontSize: 10.5, color: '#7b8798' }, splitLine: { show: false }, axisLabel: { fontSize: 10.5 } }
    ],
    series: [
      { name: '净流入(亿)', type: 'bar', stack: 'f', data: pos, itemStyle: { color: '#c0392b' }, barMaxWidth: 14 },
      { name: '净流入(亿)', type: 'bar', stack: 'f', data: neg, itemStyle: { color: '#1e8449' }, barMaxWidth: 14 },
      { name: '上证综指', type: 'line', yAxisIndex: 1, data: o.idx, showSymbol: false,
        lineStyle: { width: 1.5, color: '#1f4e79' }, itemStyle: { color: '#1f4e79' } }
    ]
  });
})();

/* 2. 分类堆叠 */
(function(){
  var b = D.broad, n = b.dates.length, st = Math.max(0, n - 60);
  var d = b.dates.slice(st);
  var series = b.cats.map(function(c, i){
    return { name: c, type: 'bar', stack: 'b', barMaxWidth: 12,
      data: b.series[c].slice(st),
      itemStyle: { color: b.colors[i] } };
  });
  CHART('cBroad', {
    grid: { left: 8, right: 12, top: 52, bottom: 34, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { type: 'scroll', top: 4, itemWidth: 10, itemHeight: 8, textStyle: { fontSize: 11 } },
    xAxis: { type: 'category', data: d, axisLabel: { fontSize: 10.5, hideOverlap: true }, axisTick: { show: false } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#eef1f6' } }, axisLabel: { fontSize: 10.5 } },
    series: series
  });
})();

/* 3. 分类累计 */
(function(){
  var b = D.broad;
  var want = ['沪深300', '科创50', '创业板指', '中证A500', '中证500', '中证1000'];
  var series = [];
  want.forEach(function(c){
    var i = b.cats.indexOf(c);
    if (i < 0) return;
    var arr = [], s = 0;
    b.series[c].forEach(function(v){ s += v; arr.push(Math.round(s)); });
    series.push({ name: c, type: 'line', data: arr, showSymbol: false,
      lineStyle: { width: 1.7, color: b.colors[i] }, itemStyle: { color: b.colors[i] } });
  });
  CHART('cBroadCum', {
    grid: { left: 8, right: 14, top: 58, bottom: 34, containLabel: true },
    tooltip: { trigger: 'axis', valueFormatter: function(v){ return v + ' 亿'; } },
    legend: { type: 'scroll', left: 'center', top: 6, itemWidth: 12, itemHeight: 8, textStyle: { fontSize: 11 } },
    xAxis: { type: 'category', data: b.dates, axisLabel: { fontSize: 10.5, hideOverlap: true }, axisTick: { show: false } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#eef1f6' } },
      axisLabel: { fontSize: 10.5 } },
    series: series
  });
})();

/* 4. 成交额 + 放量标记 */
(function(){
  var o = D.amt;
  var bar = o.amt.map(function(v, i){
    var hot = o.nf[i] != null && o.nf[i] > 100;
    return { value: v, itemStyle: { color: hot ? '#e8862e' : '#c3ccd8' } };
  });
  CHART('cAmt', {
    grid: { left: 8, right: 12, top: 58, bottom: 34, containLabel: true },
    tooltip: { trigger: 'axis' },
    legend: { data: ['成交额', '20 日均值'], top: 4, left: 0, itemWidth: 14, itemHeight: 8, textStyle: { fontSize: 11.5 } },
    xAxis: { type: 'category', data: o.d, axisLabel: { fontSize: 10.5, hideOverlap: true }, axisTick: { show: false } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#eef1f6' } }, axisLabel: { fontSize: 10.5 } },
    series: [
      { name: '成交额', type: 'bar', data: bar, barMaxWidth: 12, itemStyle: { color: '#c3ccd8' } },
      { name: '20 日均值', type: 'line', data: o.ma, showSymbol: false,
        lineStyle: { width: 1.5, type: 'dashed', color: '#1f4e79' }, itemStyle: { color: '#1f4e79' } }
    ]
  });
})();

/* 3b. 成交额双相关：强度 vs 方向 */
(function(){
  var a = D.amtcorr;
  if (!a || !a.years.length) return;
  CHART('cAmtCorr', {
    grid: { left: 8, right: 12, top: 58, bottom: 30, containLabel: true },
    tooltip: { trigger: 'axis', valueFormatter: function(v){ return v.toFixed(3); } },
    legend: { data: ['与净流入（方向）', '与 |净流入|（强度）'], top: 4, left: 0,
      itemWidth: 12, itemHeight: 8, textStyle: { fontSize: 11.5 } },
    xAxis: { type: 'category', data: a.years, axisTick: { show: false },
      axisLabel: { fontSize: 12, color: '#3f5066' } },
    yAxis: { type: 'value', min: -0.6, max: 1, interval: 0.2, splitLine: { lineStyle: { color: '#eef1f6' } },
      axisLabel: { fontSize: 10.5, formatter: function(v){ return v.toFixed(1); } } },
    series: [
      { name: '与净流入（方向）', type: 'bar', data: a.signed, barMaxWidth: 40,
        itemStyle: { color: '#1f4e79' },
        label: { show: true, position: 'top', fontSize: 11, color: '#1f4e79',
          formatter: function(p){ return p.value.toFixed(2); } },
        markLine: { silent: true, symbol: 'none', data: [{ yAxis: 0 }],
          lineStyle: { color: '#9aa5b4', width: 1 },
          label: { show: false } } },
      { name: '与 |净流入|（强度）', type: 'bar', data: a.abs, barMaxWidth: 40,
        itemStyle: { color: '#e8862e' },
        label: { show: true, position: 'top', fontSize: 11, color: '#b8691c',
          formatter: function(p){ return p.value.toFixed(2); } } }
    ]
  });
})();

/* 5. 两融 */
(function(){
  var m = D.margin, cats = m.cats;
  var cols = ['#c0392b', '#e8862e', '#1f4e79', '#1e8449'];
  CHART('cMarginBal', {
    grid: { left: 8, right: 12, top: 58, bottom: 34, containLabel: true },
    tooltip: { trigger: 'axis', valueFormatter: function(v){ return v + ' 亿'; } },
    legend: { data: ['融资余额'], top: 4, itemWidth: 12, itemHeight: 8, textStyle: { fontSize: 11.5 } },
    xAxis: { type: 'category', data: m.dates, axisLabel: { fontSize: 10.5, hideOverlap: true }, axisTick: { show: false } },
    yAxis: { type: 'value', scale: true, splitLine: { lineStyle: { color: '#eef1f6' } }, axisLabel: { fontSize: 10.5 } },
    series: [{ name: '融资余额', type: 'line', data: m.rzye[cats[0]], showSymbol: false,
      lineStyle: { width: 1.8, color: '#1f4e79' }, itemStyle: { color: '#1f4e79' },
      areaStyle: { color: 'rgba(31,78,121,.06)' } }]
  });
  CHART('cMarginFlow', {
    grid: { left: 8, right: 12, top: 58, bottom: 34, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: cats, top: 4, itemWidth: 12, itemHeight: 8, textStyle: { fontSize: 11.5 } },
    xAxis: { type: 'category', data: m.dates, axisLabel: { fontSize: 10.5, hideOverlap: true }, axisTick: { show: false } },
    yAxis: { type: 'value', name: '亿元', scale: true, nameTextStyle: { fontSize: 10.5, color: '#7b8798' },
      splitLine: { lineStyle: { color: '#eef1f6' } }, axisLabel: { fontSize: 10.5 } },
    series: cats.map(function(c, i){
      return { name: c === '全市场' ? '融资净买入' : c, type: 'bar', stack: 'm', barMaxWidth: 11,
        data: m.rzjme[c].map(function(v){ return v; }),
        itemStyle: { color: function(p){ return p.value >= 0 ? '#c0392b' : '#1e8449'; } } };
    })
  });
})();

/* 6. 20 只累计 */
(function(){
  var c = D.cum, codes = c.codes, st0 = c.start || 0;
  var pick = codes.slice(0, 5);
  var series = pick.map(function(code){
    return { name: c.names[code], type: 'line', data: c.series[code].slice(st0), showSymbol: false,
      lineStyle: { width: 1.6, color: c.colors[code] }, itemStyle: { color: c.colors[code] } };
  });

  CHART('cCum', {
    grid: { left: 8, right: 12, top: 58, bottom: 34, containLabel: true },
    tooltip: { trigger: 'axis', valueFormatter: function(v){ return v + ' 亿'; } },
    legend: { type: 'scroll', top: 4, itemWidth: 12, itemHeight: 8, textStyle: { fontSize: 11 } },
    xAxis: { type: 'category', data: c.dates.slice(st0), axisLabel: { fontSize: 10.5, hideOverlap: true }, axisTick: { show: false } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#eef1f6' } }, axisLabel: { fontSize: 10.5 } },
    series: series
  });
})();

/* 7. 逐年超额 */
(function(){
  var y = D.year, labs = y.map(function(r){ return r.year; });
  CHART('cYear', {
    grid: { left: 8, right: 12, top: 58, bottom: 30, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: function(ps){
        var s = '<b>' + ps[0].axisValue + '</b>';
        ps.forEach(function(p){
          var r = y[p.dataIndex];
          var t = p.seriesName === '5 日超额' ? r.t5 : r.t20;
          s += '<br>' + p.marker + p.seriesName + '：' + (p.value >= 0 ? '+' : '') + p.value.toFixed(2) + 'pp' +
               '（t=' + (t == null ? '—' : t) + '）';
        });
        s += '<br><span style="color:#7b8798">事件数 ' + y[ps[0].dataIndex].n + '</span>';
        return s;
      } },
    legend: { data: ['5 日超额', '20 日超额'], top: 4, left: 0, itemWidth: 12, itemHeight: 8, textStyle: { fontSize: 11.5 } },
    xAxis: { type: 'category', data: labs, axisTick: { show: false }, axisLabel: { fontSize: 11.5 } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#eef1f6' } }, axisLabel: { fontSize: 10.5 } },
    series: [
      { name: '5 日超额', type: 'bar', data: y.map(function(r){ return r.ex5; }), barMaxWidth: 26,
        itemStyle: { color: '#c0392b' }, label: { show: true, position: 'top', fontSize: 10.5,
          formatter: function(p){ return (p.value >= 0 ? '+' : '') + p.value.toFixed(2); } } },
      { name: '20 日超额', type: 'bar', data: y.map(function(r){ return r.ex20; }), barMaxWidth: 26,
        itemStyle: { color: '#1f4e79' }, label: { show: true, position: 'top', fontSize: 10.5,
          formatter: function(p){ return (p.value >= 0 ? '+' : '') + p.value.toFixed(2); } } }
    ]
  });
})();

/* 8. 滚动 β */
(function(){
  var r = D.roll;
  CHART('cRoll', {
    grid: { left: 8, right: 12, top: 58, bottom: 34, containLabel: true },
    tooltip: { trigger: 'axis', valueFormatter: function(v){ return v == null ? '—' : v; } },
    legend: { data: ['120 日 β'], top: 4, left: 0, itemWidth: 14, itemHeight: 8, textStyle: { fontSize: 11.5 } },
    xAxis: { type: 'category', data: r.dates, axisLabel: { fontSize: 10.5, hideOverlap: true }, axisTick: { show: false } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#eef1f6' } }, axisLabel: { fontSize: 10.5 } },
    series: [{
      name: '120 日 β', type: 'line', data: r.beta, showSymbol: false, connectNulls: false,
      lineStyle: { width: 1.9, color: '#1f4e79' }, itemStyle: { color: '#1f4e79' },
      areaStyle: { color: 'rgba(31,78,121,.06)' },
      markLine: { silent: true, symbol: 'none', lineStyle: { color: '#7b8798', type: 'dashed', width: 1 },
        label: { formatter: '零轴', position: 'insideEndTop', fontSize: 10.5, color: '#7b8798' },
        data: [{ yAxis: 0 }] }
    }]
  });
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    build()
