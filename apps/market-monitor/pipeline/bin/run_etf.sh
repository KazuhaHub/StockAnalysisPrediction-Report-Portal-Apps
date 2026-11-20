#!/usr/bin/env bash
# 日更 4/5：宽基 ETF 资金监测面板
#
# 08:00 跑，取到的必然是「上一交易日」收盘后披露的份额与净值，这是正常节奏不是故障。
# refresh.sh 每一步抓取失败都会沿用库内数据继续，只有 flow/metrics/build 失败才中止。

set -uo pipefail
. "$(cd "$(dirname "$0")" && pwd)/env.sh"

LOG="$(logfile etf)"
exec > >(tee -a "$LOG") 2>&1

echo "==== $(date '+%F %T') ETF 面板开始"

cd "$WS_ROOT/analysis/panel" || exit 1

bash ./refresh.sh
rc=$?

if [ "$rc" -ne 0 ]; then
  echo "!! refresh.sh 退出码 $rc"
  echo "   flow/metrics 失败是代码或数据结构问题，看上面最后几行；"
  echo "   份额/净值抓取失败只是接口临时不可用，脚本会沿用库内数据，属可接受降级。"
  exit "$rc"
fi

# 数据日期与健康度（判断"今天这版是不是新数据"用）
"$PY" - <<'PYEOF'
import json, os
p = os.path.join(os.environ["WS_ROOT"], "analysis/panel/data/metrics.json")
try:
    m = json.load(open(p))
    print("asof      :", m.get("asof") or m.get("data", {}).get("asof"))
    h = m.get("data_health") or {}
    for k, v in list(h.items())[:8]:
        print(f"health.{k}: {v}")
except Exception as e:
    print("读 metrics.json 失败:", type(e).__name__, e)
PYEOF

echo "---- 发布到 web 目录"
bash "$APP_HOME/bin/publish.sh" etf

echo "==== $(date '+%F %T') 完成"
