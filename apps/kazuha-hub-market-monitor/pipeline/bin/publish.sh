#!/usr/bin/env bash
# 把各任务的产物同步到 nginx 静态目录，并重建首页索引。
#
# 为什么单独一步而不是让各任务直接写 web/：
#   各任务自己的输出路径是「工作目录内的相对位置」，脚本里到处在用；
#   统一在这里做一次映射，改对外文件名不用动业务脚本。
#
# 用法： publish.sh [任务名]   任务名只用于日志，实际总是全量对齐（幂等）

set -uo pipefail
. "$(cd "$(dirname "$0")" && pwd)/env.sh"

which="${1:-all}"
echo "[publish] 触发来源：$which"

publish_one() {
  local name="$1" src="$2" dst="$3"
  if [ -f "$src" ]; then
    cp -f "$src" "$WEB_ROOT/$dst" && \
      echo "  ✓ $name → web/$dst  ($(du -h "$src" | cut -f1), $(date -r "$src" '+%F %H:%M'))"
  else
    echo "  · $name 源文件不存在，跳过：$src"
  fi
}

publish_one "情绪监控"   "$WS_ROOT/reports/sentiment-monitor/monitor.html"                 "sentiment.html"
publish_one "Panorama"   "$WS_ROOT/panorama/Panorama_全策略选股与十法估值.html"            "panorama.html"
publish_one "ETF资金"    "$WS_ROOT/reports/ETF国家队资金监测面板.html"                     "etf.html"
publish_one "融资盘扫描" "$APP_HOME/margin_scan/融资盘与持仓结构扫描.html"                  "margin.html"

# 重建索引页（失败不影响已发布文件）
"$PY" "$APP_HOME/bin/index_gen.py" || echo "  ! 索引页生成失败，已有文件不受影响"
