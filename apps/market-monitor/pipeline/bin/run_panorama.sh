#!/usr/bin/env bash
# 日更 3/5：Panorama 全策略选股与十法估值
#
# daily_update.sh 自带三道闸门，不要绕过它手拆步骤：
#   1) 等 .mdwrite.lock 放开（否则会拿到「一半票有今日 bar」的混合截面，因子当场错位）
#   2) 向服务端要交易日历校验新鲜度，STALE 直接 exit 2 拒绝发布
#   3) 任一步失败保留 out/last_*.log 原文，不静默重试

set -uo pipefail
. "$(cd "$(dirname "$0")" && pwd)/env.sh"

LOG="$(logfile panorama)"
exec > >(tee -a "$LOG") 2>&1

echo "==== $(date '+%F %T') Panorama 开始"

TARGET="$(target_trading_day)"
[ -n "$TARGET" ] && echo "目标交易日：$TARGET"
if ! wait_marketdata "$TARGET" 1800; then
  echo "!! 行情库未更新：末端 $(md_last_date)，目标 ${TARGET}。不发布新报告。"
  exit 3
fi

cd "$WS_ROOT/panorama" || exit 1

bash ./daily_update.sh
rc=$?

if [ "$rc" -ne 0 ]; then
  echo "!! daily_update.sh 退出码 $rc"
  case "$rc" in
    2) echo "   → STALE：行情库不是最新交易日。先修行情库更新，别用旧数据出报告。" ;;
    3) echo "   → 计算链某一步失败，看 out/last_*.log 最后一个报错。" ;;
    4) echo "   → 构建或等待超时。若提示写锁超 25 分钟，说明行情库 update 卡住了。" ;;
  esac
  for f in "$WS_ROOT"/panorama/out/last_*.log; do
    [ -f "$f" ] && { echo "--- $(basename "$f")"; tail -8 "$f"; }
  done
  exit "$rc"
fi

echo "---- 发布到 web 目录"
bash "$APP_HOME/bin/publish.sh" panorama

echo "==== $(date '+%F %T') 完成"
