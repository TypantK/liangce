#!/bin/bash
# 「量策」启动脚本
cd "$(dirname "$0")"

# 动态获取用户 Python bin 路径，避免硬编码 Python 版本号
_USER_PYTHON_BIN=$(python3 -m site --user-base 2>/dev/null)/bin
if [ -d "$_USER_PYTHON_BIN" ]; then
    export PATH="$_USER_PYTHON_BIN:$HOME/nodejs/bin:$PATH"
else
    export PATH="$HOME/Library/Python/3.9/bin:$HOME/nodejs/bin:$PATH"
fi

PORT=8501

# 选择 Python 解释器（优先用户 site 中的 python3，回退系统 /usr/bin/python3）
PY_BIN="/usr/bin/python3"
if command -v python3 >/dev/null 2>&1; then
    PY_BIN="$(command -v python3)"
fi

# 检查核心依赖（streamlit）是否可用，缺失则自动安装
if ! "$PY_BIN" -c "import streamlit" >/dev/null 2>&1; then
    echo "[量策] 未检测到 streamlit，正在安装依赖..."
    "$PY_BIN" -m pip install --user -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "[量策][错误] 依赖安装失败，请手动执行："
        echo "  $PY_BIN -m pip install --user -r requirements.txt"
        exit 1
    fi
fi

# 启动前自测门禁（离线、约 2 秒；失败仅告警，不阻断启动）
echo "运行离线自测验证（数据层 + 核心功能）..."
if "$PY_BIN" run_selfcheck.py >/dev/null 2>&1; then
    echo "自测通过：数据层与核心功能正确性已验证。"
else
    echo "[警告] 自测未完全通过，请运行 python3 run_selfcheck.py 查看详情。"
fi

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