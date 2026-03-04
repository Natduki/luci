#!/bin/sh
LOG_FILE="/var/log/sqm_controller.log"

echo "=== SQM停止 ===" >> $LOG_FILE
python3 /usr/lib/sqm-controller/main.py --disable >> $LOG_FILE 2>&1

if ip link show ifb0 >/dev/null 2>&1; then
    ip link set ifb0 down
    ip link delete ifb0
fi

echo "SQM 已停止" >> $LOG_FILE
exit 0