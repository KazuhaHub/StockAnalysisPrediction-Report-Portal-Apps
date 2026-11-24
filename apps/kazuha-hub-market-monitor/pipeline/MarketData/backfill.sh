#!/usr/bin/env bash
# 缺口补票一键驱动：拉一批 → 入库 → 再拉，直到缺口清空 → 补元数据 → 重算因子体检 → 重建报告。
#
# 为什么要循环而不是一次跑完
#   上游每秒只放几分之一只票（服务端自己还在跑 230 天没结束的 HKEX 回补），
#   2,000 只票要 4~6 小时。中途断网、机器睡眠、被 kill 都不能丢进度：
#   拉取按票记 pull_cache/done.txt，入库是幂等合并，重跑只补没补的。
#
# 和行情库日更的关系（2026-11-14 加）
#   - 拉取阶段：日更（.update.lock）在跑就暂停，别抢同一个上游额度；
#   - 入库阶段：必须拿 .mdwrite.lock（与 update.sh 共用），拿不到就跳过本轮入库，
#     数据留在 pull_cache，下一轮再灌——入库幂等，不丢东西；
#   - 日更优先：update 拿锁时若撞上我们在入库，它会等到我们写完（入库约 2 分钟）。
#
# 用法：
#   ./backfill.sh              # 后台跑（nohup 或 run_in_background）
#   ./backfill.sh --once 25    # 只跑 25 分钟的拉取就退出（给定时任务用）
set -uo pipefail
cd "$(dirname "$0")"
PY="${PY:-/opt/daily-tasks/venv/bin/python3}"
LOCK="$PWD/.backfill.lock"
PAN=/opt/daily-tasks/workspace/panorama
source ./locklib.sh

ts() { date "+%m-%d %H:%M:%S"; }
ONCE=0; MIN=25
if [[ "${1:-}" == "--once" ]]; then ONCE=1; MIN=${2:-25}; fi

# 互斥：定时任务和后台常驻可能同时醒，重复拉会互相抢上游额度
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "[$(ts)] 已有补票在跑（${LOCK}），本次退出"
  exit 0
fi
trap 'mdlock_release; rmdir "$LOCK" 2>/dev/null' EXIT
echo $$ > "$LOCK/pid"

remain() {
  $PY - <<'EOF'
import json, os, sys
sys.path.insert(0, os.getcwd())
import market_data as md
g = json.load(open("pool_gap_panorama.json", encoding="utf-8"))
codes = {md.norm_code(x["code"]) for ch in g["batches"].values() for x in ch}
have = set(md.codes())
done = set()
if os.path.exists("pull_cache/done.txt"):
    done = {l.strip() for l in open("pull_cache/done.txt") if l.strip()}
print(len(codes - have - done))
EOF
}

while true; do
  N=$(remain)
  echo "[$(ts)] 剩余缺口 $N 只"
  [[ "$N" -eq 0 ]] && break

  # 日更在跑就让路。日更单轮 3300 只要跑近 2 小时，这期间我们拉票只会让两边
  # 一起被上游限流（实测撞 429 后单票延迟翻 3~5 倍），不如等它收工。
  if md_update_running; then
    echo "[$(ts)] 行情库日更在跑，暂停拉取 60s（不抢上游额度）"
    sleep 60
    [[ "$ONCE" -eq 1 ]] && continue
    continue
  fi

  $PY bulk_pull.py --max-minutes "$MIN" --workers 4 --shard 20

  # 入库是唯一会改 bars/ 与 meta.json 的动作，必须进写锁。
  # 拿不到（日更正在写）就跳过，缓存留到下一轮，别硬写。
  if mdlock_acquire 120 "backfill-ingest"; then
    echo "[$(ts)] 入库（已持写锁）"
    $PY expand_run.py --stage ingest 2>&1 | tail -4
    mdlock_release
  else
    echo "[$(ts)] 写锁被「$(mdlock_holder)」占用，本轮跳过入库，数据留在 pull_cache"
  fi
  [[ "$ONCE" -eq 1 ]] && exit 0
  sleep 5
done

echo "[$(ts)] 缺口清空，补元数据"
if mdlock_acquire 900 "backfill-meta"; then
  $PY fetch_catalog.py --offline 2>&1 | tail -3
  $PY apply_meta_patch.py || true
  $PY market_data.py check 2>&1 | tail -3
  mdlock_release
else
  echo "[$(ts)] 写锁被「$(mdlock_holder)」占用，跳过元数据阶段，下次重跑补上"
  exit 0
fi

echo "[$(ts)] 重算因子体检（补票前后口径差异要落到报告里）"
cd "$PAN" || exit 0
$PY health.py
echo "[$(ts)] 重建报告"
ASOF=$($PY -c "from asof import asof_iso; print(asof_iso())")
$PY export_site.py > out/last_export.log 2>&1 && \
  "$PY" "$HOME/.workbuddy/skills/html-report/scripts/build_report.py" site/index.src.html "out/Panorama_${ASOF//-/}.html" > out/last_build.log 2>&1 && \
  cp -f "out/Panorama_${ASOF//-/}.html" "Panorama_全策略选股与十法估值.html" && \
  echo "[$(ts)] ✅ 报告已更新" || echo "[$(ts)] ❌ 重建失败，看 out/last_build.log"
