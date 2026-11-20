#!/usr/bin/env bash
# 卸载：停掉并移除定时任务，保留数据目录不动（行情库重建要 3 小时，别手滑删了）。
#
# 用法： sudo bash uninstall.sh

set -uo pipefail
PREFIX="${1:-/opt/daily-tasks}"
PREFIX="${PREFIX#--prefix=}"

[ "$(id -u)" -eq 0 ] || { echo "需要 root"; exit 1; }

echo "== 停止并禁用定时任务"
for t in marketdata sentiment panorama etf margin margin-guard; do
  systemctl stop "daily-$t.timer" 2>/dev/null
  systemctl disable "daily-$t.timer" 2>/dev/null
done
systemctl stop daily-stock-server.service 2>/dev/null
systemctl disable daily-stock-server.service 2>/dev/null

echo "== 移除 systemd 单元"
rm -f /etc/systemd/system/daily-*.service /etc/systemd/system/daily-*.timer
systemctl daemon-reload
systemctl reset-failed 2>/dev/null

echo "== 移除 nginx 站点"
if [ -f /etc/nginx/conf.d/daily-tasks.conf ]; then
  rm -f /etc/nginx/conf.d/daily-tasks.conf
  nginx -t >/dev/null 2>&1 && systemctl reload nginx 2>/dev/null
  echo "   已移除"
fi

# 注意：有正在跑的任务时不要删目录，否则会写坏 parquet
if pgrep -f "$PREFIX/bin/run_" >/dev/null 2>&1; then
  echo
  echo "!! 还有任务在运行，目录未删除。等它跑完再手动删："
  pgrep -af "$PREFIX/bin/run_"
  exit 0
fi

cat <<EOF

== 已卸载。数据目录保留在 ${PREFIX}：
     行情库 bars      $(du -sh "$PREFIX/MarketData/bars" 2>/dev/null | cut -f1)
     投研数据         $(du -sh "$PREFIX/workspace" 2>/dev/null | cut -f1)
     融资盘数据       $(du -sh "$PREFIX/margin_scan/data" 2>/dev/null | cut -f1)

   确认不再需要后手动删除：
     rm -rf $PREFIX
   运行用户 daily 也还在，需要的话：
     userdel daily
EOF
