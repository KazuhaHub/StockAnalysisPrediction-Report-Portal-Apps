#!/usr/bin/env bash
# 交易日增量更新：只补上一次之后的新 bar，不重下历史。
#
# 为什么要有这个脚本而不是直接调 python：
#   1) 解释器写死成 venv 里的那个，定时任务就不必记 python3 到底指向谁；
#   2) 输出同时落 logs/update-YYYYMMDD.log，失败时能直接看原因；
#   3) pending_add.txt 里的票（曾经在源端取不到）每次顺带重试，成功就自动移出。
set -u
PY=/opt/daily-tasks/venv/bin/python3
cd "${MD_HOME:-/opt/daily-tasks/MarketData}" || exit 1
source ./locklib.sh          # 写锁：与补票入库互斥，见 locklib.sh 抬头
mkdir -p logs
LOG="logs/update-$(date +%Y%m%d).log"

# 并发锁：2026-11-09 出过两个 update 同时写同一 parquet 分区互相覆盖的事故。
# 单轮 3300+ 只要跑近 2 小时，21:00 的 launchd 与 23:30 的兜底必然会撞在一起，
# 没锁就是重演。mkdir 是原子操作，抢不到就直接退出（退出码 0，不算失败）。
LOCK="$PWD/.update.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  old=$(cat "$LOCK/pid" 2>/dev/null || echo "")
  if [ -n "$old" ] && kill -0 "$old" 2>/dev/null; then
    echo "== $(date '+%F %T') 已有 update 在跑（pid ${old}），本次跳过，避免并发写同一分区"
    exit 0
  fi
  echo "== $(date '+%F %T') 清理残留锁（pid ${old:-未知} 已不在）"
  rm -rf "$LOCK"
  mkdir "$LOCK" 2>/dev/null || { echo "!! 抢锁失败，本次跳过"; exit 0; }
fi
echo $$ > "$LOCK/pid"
trap 'mdlock_release; rm -rf "$LOCK"' EXIT INT TERM

# 写锁：与补票入库（expand_run.py --stage ingest）共用。
# 两者都是「读全库 → 合并 → 整体重写 meta.json」。撞在一起不会报错，但后写者拿的是
# 自己开头读到的旧快照，会把先写者新增的票从 meta 里抹掉——bars 还在、md.codes() 看不见。
# 日更优先，所以这里愿意等（入库约 2 分钟）；15 分钟还拿不到就退出，
# 21:00 与 23:30 两趟本身互为兜底，不必硬抢。
if ! mdlock_acquire 900 "update"; then
  echo "== $(date '+%F %T') 写锁被「$(mdlock_holder)」占用超 15 分钟，本次跳过（下趟兜底）"
  exit 3
fi

{
  echo "== $(date '+%F %T') 开始增量更新"

  # 终点用「最近交易日」而不是「今天」。
  # 库里 update 默认 end=今天：周六手跑一次，4,276 只票全被判成待更新，每只都去
  # 源端要周末的 K 线、拿回 0 行，实测白烧 2.4 小时额度（2026-11-14 踩到）。
  # 换成最近交易日后，周末/节假日一轮几秒收工；顺带能一次补齐落下的多天。
  LAST=$("$PY" trading_day.py 2>/dev/null | tail -1)
  if [[ -n "$LAST" ]]; then
    END_ARGS=(--end "$LAST")
    echo "== 终点：最近交易日 $LAST"
  else
    END_ARGS=()
    echo "!! 交易日历不可用，退回「今天」为终点（周末会空跑）"
  fi

  # bash 下空数组 + set -u 直接展开会报 unbound，用 ${arr[@]+...} 兜住。
  "$PY" market_data.py update --workers 6 ${END_ARGS[@]+"${END_ARGS[@]}"}
  rc=$?
  echo "== update 退出码 $rc"

  # 每天写完之后立刻体检一次（约 1 秒，只读 code/date 两列）。
  # 它查的是"数据有没有悄悄变少、有没有落错分区"——这两类都不会让 OHLC 检查变红，
  # 2026-11-08 那次 968 只票 / 138,975 根消失就是这么漏掉的。
  # 注意 rc：脚本以前把 update 的退出码吞掉了（管道最后是 tee），
  # 定时任务永远显示成功，出问题只能靠人去翻日志。
  "$PY" market_data.py check
  crc=$?
  echo "== check 退出码 $crc"
  if [ "$crc" -ne 0 ]; then
    echo "!! 库体检没过：先别用这批数据。看上面几行，回滚用 market_data.py restore <stamp>"
    rc=$crc
  fi

  if [ -s pending_add.txt ]; then
    echo "== 重试 pending_add.txt 里的票"
    # 这个文件被写脏过：行尾带着 "# RuntimeError(...)" 的注释。整行当代码用，
    # 下面 `-c "... '001268  # RuntimeError...' in md.codes()"` 就是语法错误
    # （leading zeros / invalid syntax），于是每轮都"失败"但没人知道为什么。
    # 只留第一段、必须是 6 位数字；清洗前的版本留一份备份。
    awk '{ c=$1; if (c ~ /^[0-9]{6}$/) print c }' pending_add.txt | sort -u > pending_add.clean
    if ! cmp -s pending_add.txt pending_add.clean; then
      cp -f pending_add.txt "pending_add.txt.bak-$(date +%Y%m%d)"
      mv -f pending_add.clean pending_add.txt
      echo "   清洗 pending_add.txt（原文件已备份 .bak-$(date +%Y%m%d)）"
    else
      rm -f pending_add.clean
    fi
    while IFS= read -r code; do
      [ -z "$code" ] && continue
      case "$code" in \#*) continue ;; esac
      if "$PY" -c "import sys; sys.path.insert(0,'.'); import market_data as md; sys.exit(0 if '$code' in md.codes() else 1)"; then
        grep -v "^${code}\$" pending_add.txt > pending_add.tmp && mv pending_add.tmp pending_add.txt
        echo "   $code 已在库中，移出待办"
        continue
      fi
      if "$PY" market_data.py add "$code" --workers 1; then
        grep -v "^${code}\$" pending_add.txt > pending_add.tmp && mv pending_add.tmp pending_add.txt
        echo "   $code 补齐成功"
      else
        echo "   $code 仍失败，保留在待办"
      fi
    done < pending_add.txt
  fi

  echo "== $(date '+%F %T') 结束（退出码 ${rc}）"
} 2>&1 | tee -a "$LOG"

# 退出码必须是 update/check 的，不是 tee 的：否则定时任务拿到的永远是 0。
exit ${rc:-0}
