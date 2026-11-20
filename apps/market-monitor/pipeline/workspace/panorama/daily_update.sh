#!/usr/bin/env bash
# Panorama 日更：行情库就绪 → 主数据集 → 因子与估值 → 快照 → 对比 → 导出 → 构建
# 用法：
#   ./daily_update.sh                 # 用本地行情库最后一根 K 线
#   PANORAMA_ASOF=2026-11-12 ./daily_update.sh   # 指定日期（回补/复现）
set -euo pipefail

cd "$(dirname "$0")"
PY=/opt/daily-tasks/venv/bin/python3
OUT="out"
mkdir -p "$OUT" shots

ts() { date +%H:%M:%S; }

# ---------- 0 数据新鲜度闸门 ----------
# ASOF 是从本地 K 线推导的，「ASOF == 最后一根 K 线」是同义反复，挡不住
# 「今天是交易日但昨晚行情库更新失败」——那晚会拿旧数据算出一份看起来全新的报告。
# 所以向服务端要交易日历做真校验；显式指定 PANORAMA_ASOF（回补历史）时跳过。
# ---------- 0.0 等行情库写完 ----------
# update.sh（21:00 主跑 + 23:30 兜底）与补票 ingest 都会重写 bars/ 与 meta.json。
# 分区是 os.replace 原子替换，读不到半个 parquet；但会读到「一部分票有今日 bar、
# 一部分还没有」的混合截面——动量/波动因子当场错位，而报告看起来一切正常。
# 所以先等写锁放开再取 ASOF：ASOF 本身也是从库里推出来的，得等它定下来。
WL="$HOME/MarketData/.mdwrite.lock"
waited=0
while [[ -d "$WL" ]] && (( waited < 1500 )); do
  holder=$(cat "$WL/who" 2>/dev/null || echo "?")
  if (( waited % 60 == 0 )); then
    echo "[$(ts)] 行情库正在写入（${holder}），已等 ${waited}s"
  fi
  sleep 15
  waited=$((waited + 15))
done
if [[ -d "$WL" ]]; then
  echo "❌ 行情库写入超过 25 分钟未结束（$(cat "$WL/who" 2>/dev/null || echo '?')），拒绝在混合截面上出报告。"
  exit 4
fi

ASOF=$($PY -c "from asof import asof_iso; print(asof_iso())")
if [[ -z "${PANORAMA_ASOF:-}" ]]; then
  set +e
  FRESH=$($PY check_freshness.py 2>&1 | tail -1)
  FRESH_RC=$?
  set -e
  echo "[$(ts)] 新鲜度：$FRESH"
  if [[ "$FRESH" == STALE* ]]; then
    echo "❌ 行情库不是最新的（${FRESH}）。先跑行情库 update，本次拒绝发布。"
    exit 2
  fi
else
  echo "[$(ts)] 回补模式 PANORAMA_ASOF=${ASOF}，跳过新鲜度校验"
fi
echo "[$(ts)] ASOF=$ASOF"

# ---------- 1 计算链 ----------
run() {
  local name=$1; shift
  echo "[$(ts)] $name"
  "$@" > "$OUT/last_${name}.log" 2>&1 || { echo "❌ $name 失败，日志：$OUT/last_${name}.log"; tail -20 "$OUT/last_${name}.log"; exit 3; }
}

run master     $PY build_master.py
run compute    $PY compute.py
# health 必须排在 export 前面：体检结果（IC / 分层）会写进 data/health.json，
# export 直接把它塞进 payload。漏掉这一步，页面上的因子体检会一直是旧数。
run health     $PY health.py
run snapshot   $PY snapshot.py
run diff       $PY diff.py
run export     $PY export_site.py

# ---------- 2 构建 ----------
TAG=${ASOF//-/}
TARGET="$OUT/Panorama_${TAG}.html"
echo "[$(ts)] build → $TARGET"
"$PY" "$HOME/.workbuddy/skills/html-report/scripts/build_report.py" site/index.src.html "$TARGET" > "$OUT/last_build.log" 2>&1 \
  || { echo "❌ 构建失败"; tail -20 "$OUT/last_build.log"; exit 4; }
cp -f "$TARGET" "Panorama_全策略选股与十法估值.html"

# ---------- 3 摘要 ----------
$PY summary.py
echo "[$(ts)] ✅ 完成：$TARGET"
