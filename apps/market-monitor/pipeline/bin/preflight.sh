#!/usr/bin/env bash
# 部署自检：装完之后第一件事就是跑这个。
# 目标是把「装的时候没事、第二天凌晨才炸」的问题全部提前到装的时候暴露。
#
# 用法： bash bin/preflight.sh          只检查
#        bash bin/preflight.sh --run    检查完顺便跑一次 publish 生成索引页

set -uo pipefail
. "$(cd "$(dirname "$0")" && pwd)/env.sh"

RUN_MODE="${1:-}"
FAIL=0
WARN=0
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$1"; FAIL=$((FAIL+1)); }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; WARN=$((WARN+1)); }
sec()  { printf '\n\033[1m%s\033[0m\n' "$1"; }

sec "1. 运行环境"
[ -d "$APP_HOME" ] && ok "APP_HOME=$APP_HOME" || bad "APP_HOME 不存在：$APP_HOME"

if [ -x "$PY" ]; then
  ver="$("$PY" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])' 2>/dev/null)"
  ok "Python ${ver}（${PY}）"
  "$PY" -c 'import sys;sys.exit(0 if sys.version_info>=(3,9) else 1)' \
    && ok "版本 ≥3.9" || bad "Python 版本过低（需要 ≥3.9，pyarrow 要求）"
else
  bad "找不到虚拟环境解释器 ${PY}（先跑 install.sh）"
fi

sec "2. Python 依赖"
for m in pandas numpy pyarrow requests; do
  "$PY" -c "import $m" 2>/dev/null && ok "$m" || bad "缺 $m"
done
"$PY" -c "import akshare" 2>/dev/null && ok "akshare（融资盘扫描用）" || bad "缺 akshare"
"$PY" -c "import fastmcp" 2>/dev/null && ok "fastmcp（stock-server 用）" || warn "缺 fastmcp，8091 数据源起不来"

sec "3. 行情库数据"
if [ -f "$MD_HOME/meta.json" ]; then
  info="$("$PY" - <<PYEOF
import json
m = json.load(open("$MD_HOME/meta.json"))
n = m.get("n_codes") or len(m.get("stocks") or {})
print(m["date_range"][0], m["date_range"][1], n)
PYEOF
)"
  set -- $info
  ok "date_range $1 ~ ${2}，票数 $3"
  lag="$("$PY" -c "
import datetime
d=datetime.date.fromisoformat('$2'); print((datetime.date.today()-d).days)")"
  if [ "$lag" -le 4 ]; then ok "末端距今 ${lag} 天（正常）"
  elif [ "$lag" -le 10 ]; then warn "末端距今 ${lag} 天，可能欠了几天，跑一次 update 补上"
  else bad "末端距今 ${lag} 天，数据严重滞后：先跑 bin/run_marketdata.sh"; fi
else
  bad "缺 $MD_HOME/meta.json"
fi

n_bars=$(ls "$MD_HOME"/bars/*.parquet 2>/dev/null | wc -l | tr -d ' ')
[ "$n_bars" -ge 10 ] && ok "bars 分区 $n_bars 个年度文件" || bad "bars 分区只有 $n_bars 个，数据不全"

sec "4. 数据源服务 stock-server (:8091)"
if command -v curl >/dev/null 2>&1; then
  code=$(curl -s -o /dev/null -m 5 -w '%{http_code}' -X POST http://127.0.0.1:8091/mcp \
         -H 'Content-Type: application/json' \
         -H 'Accept: application/json, text/event-stream' \
         -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"preflight","version":"0"}}}' 2>/dev/null)
  if [ "$code" = "200" ]; then ok "8091 可访问（HTTP 200）"
  else bad "8091 返回 ${code}（systemctl status daily-stock-server 看日志）"; fi
else
  warn "没有 curl，跳过端口检查"
fi

# 交易日历要能取到，否则 update.sh 会退回「今天」当终点，周末空跑
td="$("$PY" "$MD_HOME/trading_day.py" 2>/dev/null | tail -1)"
if [ -n "$td" ]; then ok "交易日历可用，最近交易日 $td"
else bad "取不到交易日历：上游行情 API（QUOTE_API）不可达，或 8091 未起"; fi

sec "5. 各任务的输入文件"
chk() { [ -e "$2" ] && ok "$1" || bad "$1 缺失：$2"; }
chk "Panorama 构建模板"      "$WS_ROOT/panorama/site/index.src.html"
chk "Panorama 主数据集"      "$WS_ROOT/panorama/data/master_full.parquet"
chk "情绪面板源模板"          "$WS_ROOT/reports/sentiment-monitor/monitor.src.html"
chk "ETF 标的池"             "$WS_ROOT/analysis/panel/feed/universe.csv"
chk "ETF 份额库"             "$WS_ROOT/analysis/panel/data/shares.parquet"
chk "融资盘日线库"            "$APP_HOME/margin_scan/data/bars.parquet"
chk "融资盘两融库"            "$APP_HOME/margin_scan/data/margin_hist.parquet"

sec "6. HTML 构建工具"
BR="$HOME/.workbuddy/skills/html-report/scripts/build_report.py"
chk "build_report.py" "$BR"
chk "echarts.min.js"  "$HOME/.workbuddy/skills/html-report/assets/js/echarts.min.js"
chk "chart-boot.js"   "$HOME/.workbuddy/skills/html-report/assets/js/chart-boot.js"
if [ -f "$BR" ]; then
  "$PY" -c "import ast,sys;ast.parse(open(r'$BR').read())" 2>/dev/null \
    && ok "build_report.py 语法正常" || bad "build_report.py 语法错误"
fi

sec "7. 磁盘与写权限"
avail=$(df -Pk "$APP_HOME" | awk 'NR==2{printf "%.1f", $4/1048576}')
awk -v a="$avail" 'BEGIN{exit !(a>3)}' && ok "可用空间 ${avail} GB" || bad "可用空间仅 ${avail} GB（行情库每日增量约 300MB）"
for d in "$LOG_DIR" "$WEB_ROOT" "$MD_HOME"; do
  [ -w "$d" ] && ok "可写 $d" || bad "不可写 $d"
done

sec "8. 定时任务"
if command -v systemctl >/dev/null 2>&1; then
  for t in marketdata margin etf sentiment panorama; do
    if systemctl is-enabled --quiet "daily-$t.timer" 2>/dev/null; then
      nxt=$(systemctl show -p NextElapseUSecRealtime --value "daily-$t.timer" 2>/dev/null)
      ok "daily-$t.timer 已启用（下次：${nxt:-未知}）"
    else
      warn "daily-$t.timer 未启用"
    fi
  done
  systemctl is-active --quiet daily-stock-server 2>/dev/null \
    && ok "daily-stock-server 运行中" || warn "daily-stock-server 未运行"
else
  warn "没有 systemctl，跳过（非 systemd 环境？）"
fi

printf '\n\033[1m结果：%d 项失败，%d 项警告\033[0m\n' "$FAIL" "$WARN"
if [ "$FAIL" -eq 0 ]; then
  printf '\033[32m自检通过。\033[0m建议先手动跑一次 bash bin/run_%s.sh 验证端到端。\n' "marketdata"
else
  printf '\033[31m先修失败项再上线，否则凌晨的任务会静默失败。\033[0m\n'
fi

if [ "$RUN_MODE" = "--run" ]; then
  echo; bash "$APP_HOME/bin/publish.sh" preflight
fi
exit "$FAIL"
