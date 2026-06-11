#!/bin/bash

# 获取当前脚本所在目录的绝对路径
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# 切换到脚本所在目录
cd "$SCRIPT_DIR"

# 定义停止函数
cleanup() {
    # 查找 plan_manager.py 的 python 进程并强制杀死
    pids=$(pgrep -f "python.*plan_manager.py")
    echo "Caught SIGTERM/SIGINT, killing plan_manager.py..." >> shell.log
    echo $pids >> shell.log
    if [ -n "$pids" ]; then
        kill -9 $pids
	echo "kill -9 $pids" >> shell.log
    fi
    exit 0
}

# 捕获 SIGTERM 和 SIGINT 信号
trap cleanup SIGTERM SIGINT

# 启动 plan_manager.py
python plan_manager.py > plan_manager.log 2>&1 &
PY_PID=$!

# 等待 python 进程退出
wait $PY_PID

