#!/bin/bash
LOGFILE="/home/user/Projects/videocam-ai/sys_monitor/ups_status.txt"

{
  echo "[$(date)]"
  upower -i /org/freedesktop/UPower/devices/ups_hiddev0 | grep -E 'state|percentage'
  echo
} > "$LOGFILE" 2>&1