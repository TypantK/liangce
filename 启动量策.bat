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

REM 启动前自测门禁（离线、约 2 秒；失败仅告警，不阻断启动）
echo [量策] 正在运行离线自测验证（数据层 + 核心功能）...
%PY% run_selfcheck.py >nul 2>&1
if %errorlevel% equ 0 (
    echo [量策] 自测通过：数据层与核心功能正确性已验证。
) else (
    echo [量策][警告] 自测未完全通过，请运行 python run_selfcheck.py 查看详情。
)

echo [量策] 正在启动服务 (http://localhost:%PORT%)...
start "" http://localhost:%PORT%
%PY% -m streamlit run app.py --server.port %PORT% --server.headless true --browser.gatherUsageStats false

endlocal
