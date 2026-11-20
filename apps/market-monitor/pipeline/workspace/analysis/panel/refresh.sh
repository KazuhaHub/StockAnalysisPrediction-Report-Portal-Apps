#!/bin/bash
# 一键刷新：自建数据源全链路 → 重建面板
# 用法： ./refresh.sh          日更（增量）
#        ./refresh.sh --full   全量回补（首次或补历史）
set -u
cd "$(dirname "$0")" || exit 1
PY="${PY:-/opt/daily-tasks/venv/bin/python3}"
FULL=0
[ "${1:-}" = "--full" ] && FULL=1

step() { echo "── $1"; }

if [ $FULL -eq 1 ]; then
  step "1/9 交易所份额（沪市回溯 + 深市快照）"
  $PY -u feed/shares.py --backfill 2024-01-02 || echo "（份额回补异常，继续）"
  step "2/9 单位净值（全历史）"
  $PY -u feed/nav.py --backfill 2024-01-01 || echo "（净值回补异常，继续）"
  step "3/9 成交额（全历史）"
  $PY -u feed/amount.py --backfill 2024-01-01 || echo "（成交额回补异常，继续）"
  step "4/9 两融（近 90 天）"
  $PY -u feed/margin.py --backfill 2026-08-01 || echo "（两融回补异常，继续）"
else
  step "1/9 交易所份额"
  $PY -u feed/shares.py --daily || echo "（份额未更新，沿用库内数据）"
  step "2/9 单位净值"
  $PY -u feed/nav.py --daily || echo "（净值未更新，沿用库内数据）"
  step "3/9 成交额"
  $PY -u feed/amount.py --daily || echo "（成交额未更新，沿用库内数据）"
  step "4/9 两融"
  $PY -u feed/margin.py --daily || echo "（两融未更新，沿用库内数据）"
fi

step "5/9 指数"
$PY -u feed/index.py || echo "（指数未更新，沿用库内数据）"

step "6/9 净流入（份额变化 × 净值）"
$PY -u feed/flow.py || { echo "净流入计算失败，中止"; exit 1; }

step "7/9 实时行情"
$PY -u quotes.py || echo "（行情抓取失败，用收盘价回退）"

step "8/9 指标"
$PY -W ignore metrics.py || { echo "指标计算失败，中止"; exit 1; }

# MM_NO_HTML (set by the market-monitor app): metrics.json is the output;
# the page, its inlining and the page-vs-metrics self-check are skipped.
if [ "${MM_NO_HTML:-}" != "1" ]; then
step "9/9 渲染 + 内联"
$PY -W ignore build.py || exit 1
$PY "$HOME/.workbuddy/skills/html-report/scripts/build_report.py" \
    "../../reports/ETF国家队资金监测面板.html" | tail -3

step "自检：页面与指标一致性"
$PY selfcheck.py --quiet || echo "（自检有失败项，见上）"
else
step "9/9 渲染：skipped (MM_NO_HTML)"
fi

echo "✓ 完成 $(date '+%Y-%m-%d %H:%M:%S')"
