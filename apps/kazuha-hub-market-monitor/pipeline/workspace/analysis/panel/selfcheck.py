#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""面板自检：机械校验「渲染出来的 HTML」与「metrics.json」是否一致。

用途：每次 refresh.sh 之后跑一遍，避免出现「指标算了但页面没展示」「页面数字与数据源
不一致」「占位符没替换干净」「图表容器漏挂」这类静默故障。

用法：
    python3 selfcheck.py            # 检查 reports/ETF国家队资金监测面板.html
    python3 selfcheck.py --quiet    # 只打印失败项

退出码：0 全过；1 有失败项。
"""
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
HTML = os.path.join(ROOT, "reports", "ETF国家队资金监测面板.html")
METRICS = os.path.join(HERE, "data", "metrics.json")

ok, fail = [], []


def chk(cond, name, detail=""):
    (ok if cond else fail).append((name, detail))


def main():
    quiet = "--quiet" in sys.argv
    if not os.path.exists(HTML):
        print("找不到 %s，先跑 build.py" % HTML)
        return 1
    M = json.load(open(METRICS, encoding="utf-8"))
    H = io.open(HTML, encoding="utf-8").read()

    # ---------- 1. 占位符与资源 ----------
    # echarts 内部有 ___EC__COMPONENT__CONTAINER___ 这类标记，不是我们的占位符，先剔除
    H_clean = re.sub(r"___EC__[A-Z_]+___", "", H)
    left = re.findall(r"__[A-Z][A-Z0-9_]*[A-Z0-9]__", H_clean)
    chk(not left, "无未替换占位符", "残留: %s" % sorted(set(left))[:6])
    ext = re.search(r'<(?:script|link|img)[^>]+(?:src|href)\s*=\s*"https?://', H)
    chk(not ext, "无外链依赖（可离线）",
        ext.group(0)[:70] if ext else "")

    # ---------- 2. 图表挂载 ----------
    containers = set(re.findall(r'id="(c[A-Za-z]+)"\s+class="chart', H))
    mounts = set(re.findall(r"CHART\('([A-Za-z]+)'", H))
    chk(containers and containers == mounts, "图表容器与 CHART 调用一一对应",
        "容器%d / 挂载%d，差集 %s" % (len(containers), len(mounts),
                                    (containers ^ mounts) or "无"))

    # ---------- 3. 首屏关键数字 ----------
    cur, h = M["current"], M["health"]

    def has(txt):
        return txt in H

    chk(has("%+.1f" % cur["last_nf"]), "最新单日净流入", "%+.1f" % cur["last_nf"])
    chk(has("%+.0f" % cur["last5"]), "近 5 日累计", "%+.0f" % cur["last5"])
    chk(has("%+.0f" % cur["last20"]), "近 20 日累计", "%+.0f" % cur["last20"])
    chk(has(h["label"]), "状态灯标签", h["label"])
    chk(has("%+d" % h["score"]), "状态灯评分", "%+d" % h["score"])

    # ---------- 4. 表格行数 ----------
    n_ev = sum(1 for r in M["yearly"] for k in ("h5", "h20") if r[k])
    sec_ev = H.split("事件研究明细")[-1] if "事件研究明细" in H else ""
    chk(sec_ev.count("<tr>") - 1 >= n_ev, "事件研究明细行数", "期望 %d 行" % n_ev)

    chk(len(M.get("outflow") or {}) == 2 and "反向检验" in H, "净流出侧检验已展示")
    chk(len(M.get("beta_year") or []) == 3 and "逐年 β" in H, "逐年 β 已展示")

    td = M.get("thresh_diag") or []
    chk(len(td) == 3, "阈值时效性 3 年", "实际 %d" % len(td))
    ts = M.get("thresh_sens") or {}
    n_cells = sum(len(r["cells"]) for r in ts.get("rows", []))
    chk(n_cells == 12, "敏感性矩阵 3×4 格", "实际 %d" % n_cells)
    ad = (M.get("amt_diag") or {}).get("byyear") or []
    chk(len(ad) == 3, "成交额诊断 3 年", "实际 %d" % len(ad))

    # ---------- 5. 热力表与分类合计一致 ----------
    b = M["broad"]
    i = len(b["dates"]) - 1
    tot = sum(b["series"][c][i] for c in b["cats"])
    chk(abs(tot - b["total"][i]) < 1.0, "分类明细之和 = 合计",
        "明细 %.1f vs 合计 %.1f" % (tot, b["total"][i]))

    # ---------- 6. 数据新鲜度一致性 ----------
    dh = M.get("data_health", {})
    chk(dh.get("share_last") == M["asof"], "asof = 份额最新日",
        "%s vs %s" % (M["asof"], dh.get("share_last")))
    # 成交额可以比份额新一天（盘后即有），但不能更旧
    chk(dh.get("amount_last", "") >= dh.get("share_last", ""), "成交额不旧于份额",
        "%s vs %s" % (dh.get("amount_last"), dh.get("share_last")))

    # ---------- 7. 文案硬编码残留 ----------
    bad = [w for w in ("已连续 0 个交易日", "第 17 天连续", "2024-01-02 起完整历史")
           if w in H]
    chk(not bad, "无语病/过期硬编码文案", str(bad) if bad else "")

    # ---------- 输出 ----------
    if not quiet:
        for n, d in ok:
            print("  ✓ %s%s" % (n, ("  " + d) if d else ""))
    for n, d in fail:
        print("  ✗ %s%s" % (n, ("  " + d) if d else ""))
    print("\n%d 通过 / %d 失败" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
