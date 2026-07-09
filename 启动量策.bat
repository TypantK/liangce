@echo off
chcp 65001 >nul
REM 「量策」Windows 启动脚本
setlocal
cd /d "%~dp0"

set PORT=8501

REM 优先使用项目内的虚拟环境
if exist ".venv\Scripts\python.exe" (
    set PY=.venv\Scripts\python.exe
) else (
    echo [量策] 未找到 .venv，请先创建虚拟环境并安装依赖：
    echo   py -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

REM 检查 streamlit 是否可用
%PY% -c "import streamlit" 2>nul || (
    echo [量策] 未检测到 streamlit，正在安装依赖...
    %PY% -m pip install -r requirements.txt
)

echo [量策] 正在启动服务 (http://localhost:%PORT%)...
start "" http://localhost:%PORT%
%PY% -m streamlit run app.py --server.port %PORT% --server.headless true --browser.gatherUsageStats false

endlocal
