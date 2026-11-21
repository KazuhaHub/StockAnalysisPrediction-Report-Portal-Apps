#!/usr/bin/env bash
# usage: shot_one.sh tab outname [height]
TAB=$1; OUT=$2; H=${3:-2400}
F="/opt/daily-tasks/workspace/panorama/Panorama_全策略选股与十法估值.html"
U="/tmp/pc-$OUT-$(date +%s)"
IMG="/opt/daily-tasks/workspace/panorama/shots/$OUT.png"
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
  --user-data-dir="$U" \
  --window-size=1280,$H --virtual-time-budget=9000 \
  --screenshot="$IMG" \
  "file://$F?c=$(date +%s)#$TAB" >/dev/null 2>&1 &
CPID=$!
for i in {1..60}; do
  [ -f "$IMG" ] && sleep 1.2 && break
  sleep 0.4
done
kill $CPID 2>/dev/null
pkill -f "headless.*$OUT" 2>/dev/null
echo "$OUT $([ -f "$IMG" ] && echo ok || echo FAIL)"
