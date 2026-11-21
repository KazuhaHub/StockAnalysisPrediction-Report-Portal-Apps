#!/usr/bin/env bash
# 日更 5/5：融资盘 · 持仓结构扫描
#
# 09:00 主跑（等深交所 T+1 上午披露）。原 Mac 上另有一个 09:15 的 WorkBuddy 自动化做校验兜底，
# 这里把它脚本化成 margin_guard.sh，由 09:50 的 timer 调用：只在今天没成功更新时才补跑。

set -uo pipefail
. "$(cd "$(dirname "$0")" && pwd)/env.sh"

LOG="$(logfile margin)"
exec > >(tee -a "$LOG") 2>&1

echo "==== $(date '+%F %T') 融资盘扫描开始"
cd "$APP_HOME/margin_scan" || { echo "!! 找不到 margin_scan 目录"; exit 1; }

bash ./update.sh
rc=$?

if [ "$rc" -eq 0 ]; then
  echo "---- 发布到 web 目录"
  bash "$APP_HOME/bin/publish.sh" margin
else
  echo "!! update.sh 退出码 ${rc}，详见 $APP_HOME/margin_scan/logs/$(date +%F).log"
fi

echo "==== $(date '+%F %T') 结束 rc=$rc"
exit "$rc"
