#!/bin/bash
# 「量策」启动脚本
cd "$(dirname "$0")"
export PATH="$HOME/Library/Python/3.9/bin:$HOME/nodejs/bin:$PATH"

PORT=8501

# 关掉旧实例
OLD_PID=$(lsof -i :$PORT -sTCP:LISTEN -t 2>/dev/null | head -1)
if [ -n "$OLD_PID" ]; then
    echo "关闭旧实例 (PID: $OLD_PID)..."
    kill "$OLD_PID" 2>/dev/null
    sleep 1
fi

echo "启动服务..."
/usr/bin/python3 -m streamlit run app.py \
    --server.port "$PORT" \
    --server.headless true \
    --server.runOnSave true \
    --browser.gatherUsageStats false \
    > /tmp/量策_server.log 2>&1 &

# 等服务就绪
for i in $(seq 1 15); do
    if curl -s -o /dev/null "http://localhost:$PORT" 2>/dev/null; then
        break
    fi
    sleep 0.5
done

# 用 macOS 原生 open 启动 Chrome 原生窗口
open -n -a "Google Chrome" --args --app="http://localhost:$PORT" --window-size=1280,850

echo "「量策」已启动"