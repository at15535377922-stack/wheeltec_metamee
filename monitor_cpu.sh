#!/bin/bash

# 日志目录
LOG_DIR="/home/wheeltec/metamee/cpu_monitor"
mkdir -p $LOG_DIR

# 日志文件（每天一个）
LOG_FILE="$LOG_DIR/cpu_usage_$(date +%F).log"

# 获取 CPU 使用率
CPU_USAGE=$(top -bn1 | grep "Cpu(s)" | awk '{print 100 - $8}')

# 获取负载均值
LOAD_AVG=$(uptime | awk -F'load average:' '{print $2}' | sed 's/^ //')

# 时间戳
TIME=$(date "+%Y-%m-%d %H:%M:%S")

# 写入日志
echo "$TIME | CPU: ${CPU_USAGE}% | LoadAvg: $LOAD_AVG" >> $LOG_FILE

