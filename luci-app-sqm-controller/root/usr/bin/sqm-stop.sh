#!/bin/sh
# SQM控制器停止脚本

LOG_FILE="/var/log/sqm-controller.log"
PID_FILE="/var/run/sqm-controller.pid"

echo "停止SQM流量控制..." >> $LOG_FILE

# 停止Python程序
if [ -f "$PID_FILE" ]; then
    PID=$(cat $PID_FILE)
    kill $PID 2>/dev/null
    rm -f $PID_FILE
fi

# 清除TC规则
python3 /usr/lib/sqm-controller/main.py --disable >> $LOG_FILE 2>&1

echo "SQM流量控制已停止" >> $LOG_FILE