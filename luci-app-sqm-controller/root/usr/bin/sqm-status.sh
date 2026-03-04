#!/bin/sh
# SQM控制器状态脚本

CONFIG_FILE="/etc/config/sqm-controller"

echo "=== SQM流量控制状态 ==="
echo ""

# 检查配置文件
if [ -f "$CONFIG_FILE" ]; then
    echo "配置信息:"
    echo "  配置文件: $CONFIG_FILE"
    
    # 读取配置
    grep -E '(enabled|interface|upload_bandwidth|download_bandwidth|algorithm)' $CONFIG_FILE | \
        while read line; do
            echo "  $line"
        done
else
    echo "配置文件不存在: $CONFIG_FILE"
fi

echo ""
echo "TC规则状态:"
tc -s qdisc show 2>/dev/null || echo "  tc命令未找到或未安装"