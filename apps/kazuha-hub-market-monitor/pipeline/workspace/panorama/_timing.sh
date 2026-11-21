#!/usr/bin/env bash
PY=/opt/daily-tasks/venv/bin/python3
for s in fetch_quotes fetch_tencent build_master compute health; do
  /usr/bin/time -p $PY $s.py > /tmp/t_$s.log 2>&1
  echo "$s $(grep '^real' /tmp/t_$s.log | awk '{print $2}')s"
done
