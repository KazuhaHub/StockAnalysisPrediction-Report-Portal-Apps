#!/usr/bin/env bash
# 所有日更任务的公共环境。
#
# 核心一件事：把 HOME 指到 APP_HOME。
# 原脚本里大量出现 ~/MarketData、~/.workbuddy/skills/html-report 这类写法，
# 只要 HOME 对了，这些相对定位就全部自动成立，不需要逐处改写。
# systemd 单元里也设了 Environment=HOME=...，这里再设一遍是为了手动执行时一致。

APP_HOME="${APP_HOME:-/opt/daily-tasks}"

export APP_HOME
export HOME="$APP_HOME"
export MD_HOME="${MD_HOME:-$APP_HOME/MarketData}"
export WS_ROOT="${WS_ROOT:-$APP_HOME/workspace}"
export PY="${PY:-$APP_HOME/venv/bin/python3}"
export LOG_DIR="${LOG_DIR:-$APP_HOME/logs}"
export WEB_ROOT="${WEB_ROOT:-$APP_HOME/web}"

export PATH="$APP_HOME/venv/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PYTHONIOENCODING=utf-8
export PYTHONUNBUFFERED=1
# 生产机默认可能是 C/POSIX，中文文件名与日志会乱码或直接报错
export LANG="${LANG:-C.UTF-8}"
export LC_ALL="${LC_ALL:-C.UTF-8}"

mkdir -p "$LOG_DIR" "$WEB_ROOT"

# 统一的日志落盘：$1=任务名，之后所有输出都追加到 logs/<任务名>-YYYYMMDD.log
# 用法： exec > >(tee -a "$(logfile marketdata)") 2>&1
logfile() {
  printf '%s/%s-%s.log\n' "$LOG_DIR" "$1" "$(date +%Y%m%d)"
}

# 读行情库末端日期，失败返回空
md_last_date() {
  "$PY" -c "import json,sys
try:
    print(json.load(open('$MD_HOME/meta.json'))['date_range'][1])
except Exception:
    print('')" 2>/dev/null
}

# 目标交易日：默认「昨天及之前最近的那个交易日」
target_trading_day() {
  local base
  base=$("$PY" -c "import datetime;print((datetime.date.today()-datetime.timedelta(days=1)).isoformat())" 2>/dev/null)
  "$PY" "$MD_HOME/trading_day.py" "$base" 2>/dev/null | tail -1
}

# 等行情库就绪：末端 >= 目标交易日。最多等 $2 秒（默认 1800）
wait_marketdata() {
  local target="$1" wait_s="${2:-1800}" end waited=0
  while :; do
    end="$(md_last_date)"
    if [ -n "$end" ] && [ ! "$end" \< "$target" ]; then
      echo "[$(date '+%F %T')] 行情库已就绪：末端 $end ≥ 目标 $target"
      return 0
    fi
    if [ "$waited" -ge "$wait_s" ]; then
      echo "[$(date '+%F %T')] 行情库未就绪：末端 ${end:-未知} < 目标 ${target}，已等 ${waited}s，放弃" >&2
      return 1
    fi
    echo "[$(date '+%F %T')] 等待行情库… 末端 ${end:-未知}，目标 ${target}（已等 ${waited}s）"
    sleep 300
    waited=$((waited + 300))
  done
}
