#!/bin/bash
# 融资盘 · 持仓结构扫描 —— 日常更新
# 用法：bash update.sh              常规更新（两融增量 + 日线全量 + 结构层，约 8 分钟）
#       bash update.sh --fast       只更新两融与行情，跳过耗时的质押明细（约 3 分钟）
#       bash update.sh --refresh-spot  额外强制刷新全市场快照（股本底表校准时才需要）
# 输出：融资盘与持仓结构扫描.html（原地覆盖）+ logs/YYYY-MM-DD.log

set -e -o pipefail
trap 'rc=$?; echo "[$(date "+%H:%M:%S")] 失败，退出码 $rc"; notify "融资盘扫描更新失败" "退出码 ${rc}，详见 logs/$(date +%Y-%m-%d).log"' ERR

cd "$(dirname "$0")"
mkdir -p logs

# launchd 环境极简：PATH 仅 /usr/bin:/bin:/usr/sbin:/sbin，且可能没有 HOME/LANG
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export HOME="${HOME:-/opt/daily-tasks}"
export LANG="${LANG:-zh_CN.UTF-8}"
export LC_ALL="${LC_ALL:-zh_CN.UTF-8}"

PY=/opt/daily-tasks/venv/bin/python3
BUILD="$HOME/.workbuddy/skills/html-report/scripts/build_report.py"
OUT="融资盘与持仓结构扫描.html"
LOG="logs/$(date +%Y-%m-%d).log"

FILTER() { grep -v "NotOpenSSL\|warnings.warn\|it/s\|big_df" || true; }
notify() { echo "[$(date "+%H:%M:%S")] [NOTIFY] $1 | $2"; }   # Linux 无桌面通知，落日志

# 并发锁：定时任务与手动执行撞车时，后来者直接退出，避免同时写 parquet
LOCK=.update.lock
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
  echo "[$(date "+%H:%M:%S")] 已有更新在运行（pid $(cat "$LOCK")），本次跳过"
  exit 0
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

# 终端与日志同时输出
exec > >(tee -a "$LOG") 2>&1

FAST=0
if [ "$1" = "--fast" ]; then FAST=1; fi

echo
echo "==================================================="
echo "[$(date "+%Y-%m-%d %H:%M:%S")] 开始更新  fast=$FAST"
echo "env: PWD=$PWD  HOME=$HOME  LANG=$LANG  UID=$(id -u)"
echo "==================================================="

echo "== 1/5 抓取两融底数据（日线原子写入 + 覆盖率闸门）=="
$PY fetch_data.py --refresh-bars "$@" 2>&1 | FILTER

if [ $FAST -eq 0 ]; then
  echo "== 2/5 抓取持仓结构数据（质押明细最慢，约 4 分钟）=="
  $PY fetch_extra.py 2>&1 | FILTER
  $PY fetch_fix.py 2>&1 | FILTER
else
  echo "== 2/5 跳过持仓结构抓取（--fast），沿用既有缓存 =="
fi

echo "== 3/5 计算指标（含成本线共振带）=="
$PY build_data.py 2>&1 | FILTER

echo "== 4/5 同步 payload =="
cp out/payload.js src/

echo "== 5/5 构建单文件 HTML =="
$PY "$BUILD" src/index.html "$OUT" 2>&1 | tail -4

SIZE=$($PY -c "import os;print('%.1fMB'%(os.path.getsize(r'''$OUT''')/1048576))" 2>/dev/null || echo "?")
BASEDATE=$($PY -c "import json;print(json.load(open('out/payload.json'))['meta']['as_of'])" 2>/dev/null || echo "?")
echo "[$(date "+%H:%M:%S")] 完成 -> $OUT  size=$SIZE  basis=$BASEDATE"
notify "融资盘扫描已更新" "基准日 $BASEDATE · $SIZE"
