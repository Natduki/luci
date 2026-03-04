#!/bin/sh
LOG_FILE="/var/log/sqm_controller.log"
CONFIG_FILE="/etc/config/sqm_controller"

echo "=== SQM启动 ===" >> $LOG_FILE
. /lib/functions.sh
config_load sqm_controller

config_get enabled basic_config enabled 0
[ "$enabled" != "1" ] && {
    echo "未启用，跳过" >> $LOG_FILE
    exit 0
}

echo "执行启用..." >> $LOG_FILE
python3 /usr/lib/sqm-controller/main.py --enable >> $LOG_FILE 2>&1

if [ $? -eq 0 ]; then
    echo "SQM 已启用" >> $LOG_FILE
    exit 0
else
    echo "SQM 启用失败" >> $LOG_FILE
    exit 1
fi
