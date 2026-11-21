#!/usr/bin/env bash
# 融资盘扫描的兜底校验（对应原 Mac 上 09:15 那条 WorkBuddy 自动化）
#
# 只在「今天没成功更新」时才补跑，不要例行重跑：全量一次 8-9 分钟，
# 而且会重新抓全市场日线，无意义地压上游接口。
#
# 三种判定：
#   1) generated_at 是今天 → 正常，只回报，不跑
#   2) generated_at 不是今天 → 09:00 那次没跑成（服务没起、被 OOM、上游挂了），补跑
#   3) generated_at 是今天但 as_of 落后 → 深交所 T+1 数据还没披露，属时滞不是故障，不重跑

set -uo pipefail
. "$(cd "$(dirname "$0")" && pwd)/env.sh"

LOG="$(logfile margin-guard)"
exec > >(tee -a "$LOG") 2>&1

cd "$APP_HOME/margin_scan" || exit 1
PAYLOAD="out/payload.json"

read_meta() {
  "$PY" - <<'PYEOF' 2>/dev/null
import json
try:
    m = json.load(open("out/payload.json"))["meta"]
    print(m.get("generated_at", ""), "|", m.get("as_of", ""), "|", m.get("n", ""))
except Exception:
    print("|")
PYEOF
}

INFO="$(read_meta)"
GEN="${INFO%%|*}"
GEN="$(printf '%s' "$GEN" | tr -d ' ')"
AS_OF="$(printf '%s' "$INFO" | cut -d'|' -f2 | tr -d ' ')"
TODAY="$(date +%F)"

echo "==== $(date '+%F %T') 兜底校验"
echo "payload: generated_at=${GEN:-无}  as_of=${AS_OF:-无}  n=$(printf '%s' "$INFO" | cut -d'|' -f3)"

case "$GEN" in
  "$TODAY"*)
    echo "→ 今天已成功更新，不重跑。as_of=$AS_OF"
    exit 0
    ;;
  "")
    echo "→ payload.json 缺失或损坏，直接补跑"
    ;;
  *)
    echo "→ generated_at 不是今天（${GEN}），说明 09:00 那次没成功，补跑"
    ;;
esac

bash ./update.sh
rc=$?
if [ "$rc" -eq 0 ]; then
  echo "→ 补跑完成：$(read_meta)"
  bash "$APP_HOME/bin/publish.sh" margin
else
  echo "!! 补跑失败 rc=$rc"
  tail -40 "logs/$(date +%F).log" 2>/dev/null
fi
exit "$rc"
