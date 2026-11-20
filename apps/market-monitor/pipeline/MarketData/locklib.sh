#!/usr/bin/env bash
# 行情库「写锁」：改 bars/ 或 meta.json 的动作互斥。
#
# 为什么需要额外一把锁，而不是复用 .update.lock / .backfill.lock
#   那两把是「同一个脚本不要跑两份」的自斥锁，彼此不认识。而 `market_data.py update`
#   和 `expand_run.py --stage ingest` 是同一类操作：**读全库 → 合并 → 写回 meta.json**。
#   两者同时跑会有两个后果，且都不报错：
#     1) meta.json 是整体重写（_read_meta → 改 → _write_meta）。后写者拿到的是自己开头
#        读到的旧快照，于是先写者新增的票在 meta 里被抹掉。bars 还在，但 md.codes()
#        看不见它们——补票脚本会以为没补过，无限重拉，缺口永远不归零。
#     2) 写入前的 snapshot「只增不减」校验两边拿同一个基线算，会互相误判成数据丢失。
#
# 用法（两个脚本都先 cd 到 MarketData）：
#   source ./locklib.sh
#   mdlock_acquire 300 "update" || exit 3    # 最多等 300 秒
#   trap 'mdlock_release' EXIT INT TERM
#   mdlock_release
#
# 优先级约定：日更（update.sh）优先，补票（backfill）在拿不到锁时**放弃本轮入库**，
# 数据留在 pull_cache 里，下一轮再灌——入库是幂等的，不丢东西。

MDLOCK="$PWD/.mdwrite.lock"
MDLOCK_HELD=0

mdlock_acquire() {
  local wait_s=${1:-300} who=${2:-$0} waited=0 pid
  while true; do
    if mkdir "$MDLOCK" 2>/dev/null; then
      printf '%s\n' $$ > "$MDLOCK/pid"
      printf '%s\n' "$who" > "$MDLOCK/who"
      printf '%s\n' "$(date '+%F %T')" > "$MDLOCK/at"
      MDLOCK_HELD=1
      return 0
    fi
    pid=$(cat "$MDLOCK/pid" 2>/dev/null || true)
    if [[ -n "$pid" ]] && ! kill -0 "$pid" 2>/dev/null; then
      printf '%s\n' "清理残留写锁（pid $pid 已不在）"
      rm -rf "$MDLOCK"
      continue
    fi
    if (( waited >= wait_s )); then
      return 1
    fi
    sleep 5
    waited=$((waited + 5))
  done
}

mdlock_release() {
  if (( ${MDLOCK_HELD:-0} )); then
    rm -rf "$MDLOCK"
    MDLOCK_HELD=0
  fi
}

mdlock_holder() {
  local h
  h=$(cat "$MDLOCK/who" 2>/dev/null || true)
  printf '%s\n' "${h:-?}"
}

mdlock_busy() {
  local pid
  [[ -d "$MDLOCK" ]] || return 1
  pid=$(cat "$MDLOCK/pid" 2>/dev/null || true)
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null && return 0
  return 1
}

# 日更是否在跑（补票要给它让路：同一个上游，抢额度只会两边都慢）
md_update_running() {
  local l="$PWD/.update.lock" pid
  [[ -d "$l" ]] || return 1
  pid=$(cat "$l/pid" 2>/dev/null || true)
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null && return 0
  return 1
}
