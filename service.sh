#!/bin/bash

# --- 配置区 ---
APP_DIR="/mnt/geetest-v4-crack/ky/word"
PYTHON_BIN="python3.10"
APP_FILE="flask_word.py"
PORT=5008
LOG_FILE="$APP_DIR/flask_word.log"

cd $APP_DIR || exit 1

# --- 停止函数 ---
stop_service() {
    echo "检查端口 $PORT ..."
    PID=$(lsof -t -i:$PORT)

    if [ -n "$PID" ]; then
        echo "发现运行中的服务 PID=$PID ，正在停止..."
        kill -15 $PID

        for i in {1..10}; do
            if ! lsof -i:$PORT > /dev/null; then
                echo "服务已成功停止"
                return
            fi
            echo "等待端口释放 ($i/10)..."
            sleep 1
        done

        echo "强制终止进程..."
        kill -9 $PID
    else
        echo "服务未运行"
    fi
}

# --- 启动函数 ---
start_service() {

    echo "启动服务..."

    nohup $PYTHON_BIN $APP_FILE > $LOG_FILE 2>&1 &

    echo "等待服务启动..."
    for i in {1..15}; do
        if lsof -i:$PORT > /dev/null; then
            echo "--------------------------------------"
            echo "服务启动成功"
            echo "端口: $PORT"
            echo "日志: $LOG_FILE"
            echo "--------------------------------------"
            return
        fi
        sleep 1
    done

    echo "启动失败，请检查日志:"
    echo "$LOG_FILE"
}

# --- 参数处理 ---

if [ "$1" == "-stop" ]; then
    stop_service
    exit 0
fi

if [ "$1" == "-start" ] || [ -z "$1" ]; then
    stop_service
    start_service
    exit 0
fi

echo "用法:"
echo "./service.sh -start   启动或重启"
echo "./service.sh -stop    停止"