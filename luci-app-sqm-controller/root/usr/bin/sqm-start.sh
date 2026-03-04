#!/bin/sh
# SQM控制器启动脚本

CONFIG_FILE="/etc/config/sqm-controller"
LOG_FILE="/var/log/sqm-controller.log"
PID_FILE="/var/run/sqm-controller.pid"

# 检查配置文件
if [ ! -f "$CONFIG_FILE" ]; then
    echo "配置文件不存在: $CONFIG_FILE"
    exit 1
fi

# 读取配置
INTERFACE=$(grep '"interface"' $CONFIG_FILE | cut -d'"' -f4 2>/dev/null || echo "eth0")
UPLOAD=$(grep '"upload_bandwidth"' $CONFIG_FILE | cut -d':' -f2 | tr -d ' ,' 2>/dev/null || echo "100000")
DOWNLOAD=$(grep '"download_bandwidth"' $CONFIG_FILE | cut -d':' -f2 | tr -d ' ,' 2>/dev/null || echo "100000")
ALGORITHM=$(grep '"algorithm"' $CONFIG_FILE | cut -d'"' -f4 2>/dev/null || echo "fq_codel")

echo "启动SQM流量控制..." >> $LOG_FILE
echo "接口: $INTERFACE" >> $LOG_FILE
echo "上传: $UPLOAD Kbps" >> $LOG_FILE
echo "下载: $DOWNLOAD Kbps" >> $LOG_FILE
echo "算法: $ALGORITHM" >> $LOG_FILE

# 执行Python脚本
python3 /usr/lib/sqm-controller/main.py \
    --config "$CONFIG_FILE" \
    --interface "$INTERFACE" \
    --enable >> $LOG_FILE 2>&1

if [ $? -eq 0 ]; then
    echo "SQM流量控制启动成功" >> $LOG_FILE
    echo $$ > $PID_FILE
    exit 0
else
    echo "SQM流量控制启动失败" >> $LOG_FILE
    exit 1
fi