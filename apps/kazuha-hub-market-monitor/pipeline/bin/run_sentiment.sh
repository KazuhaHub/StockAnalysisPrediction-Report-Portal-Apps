#!/usr/bin/env bash
# 日更 2/5：市场情绪每日监控面板
#
# 顺序不能变：
#   1) 等行情库就绪（本任务 00:40 跑，处理的是昨天收盘；行情库 21:00/23:30 才落库）
#   2) sentiment_daily.py 先重建 panel.csv 再算五维读数
#   3) 必须从 monitor.src.html 复制一份再内联，不能在产物 monitor.html 上重复 build，
#      否则 echarts 会被反复内联，文件越滚越大（原自动化里踩过）

set -uo pipefail
. "$(cd "$(dirname "$0")" && pwd)/env.sh"

LOG="$(logfile sentiment)"
exec > >(tee -a "$LOG") 2>&1

echo "==== $(date '+%F %T') 情绪面板开始"

TARGET="$(target_trading_day)"
if [ -z "$TARGET" ]; then
  echo "!! 取不到目标交易日（trading_day.py 失败，检查上游行情 API 可达性）"
  exit 2
fi
echo "目标交易日：$TARGET"

if ! wait_marketdata "$TARGET" 1800; then
  echo "!! 行情库未更新：末端 $(md_last_date)，目标 ${TARGET}。本轮不出报告，避免用旧数据冒充新数据。"
  echo "!! 排查：tail -5 $MD_HOME/updates.jsonl   看是否 aborted:\"source\""
  tail -3 "$MD_HOME/updates.jsonl" 2>/dev/null
  exit 3
fi

cd "$WS_ROOT" || exit 1

echo "---- 1/3 重建情绪面板 + 计算监控状态"
"$PY" analysis/sentiment_daily.py || { echo "!! sentiment_daily.py 失败"; exit 4; }

echo "---- 2/3 构建单文件 HTML"
cd "$WS_ROOT/reports/sentiment-monitor" || exit 1
cp -f monitor.src.html monitor.html
"$PY" "$HOME/.workbuddy/skills/html-report/scripts/build_report.py" monitor.html
brc=$?
if [ "$brc" -ne 0 ]; then
  echo "!! build_report 失败（rc=${brc}），页面未发布。检查 assets/monitor.js 的 JS 语法"
  exit 5
fi

echo "---- 3/3 发布到 web 目录"
bash "$APP_HOME/bin/publish.sh" sentiment

echo "==== $(date '+%F %T') 完成"
