#!/usr/bin/env bash
# 日更 1/5：行情库增量更新
# 原实现在 Mac 上是 launchd 21:00 主跑 + WorkBuddy 自动化 23:30 兜底。
# 这里两者合并：systemd timer 同时排 21:00 和 23:30，靠 .update.lock 防并发，
# 第二趟只会补第一趟之后的差异，通常几分钟收工。

set -uo pipefail
. "$(cd "$(dirname "$0")" && pwd)/env.sh"

LOG="$(logfile marketdata)"
exec > >(tee -a "$LOG") 2>&1

echo "==== $(date '+%F %T') 行情库增量更新开始"

cd "$MD_HOME" || { echo "!! 找不到行情库目录 $MD_HOME"; exit 1; }

# update.sh 内部已包含：并发锁、写锁、交易日终点、体检、pending_add 重试
bash ./update.sh
rc=$?

echo "==== $(date '+%F %T') 结束 rc=$rc  日志：$LOG"
if [ "$rc" -ne 0 ]; then
  echo "!! 非零退出。常见原因：stock-server(:8091) 不可用、上游行情 API（QUOTE_API，默认 https://quotes.anchan.kazuhahub.com）故障、库体检未过。"
  echo "!! 排查：curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8091/mcp"
fi
exit "$rc"
