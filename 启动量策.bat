@echo off
chcp 65001 >nul
REM 「量策」Windows 启动脚本
setlocal
cd /d "%~dp0"

set PORT=8501

REM 选择 Python 解释器：优先项目内 venv，否则回退系统 python / py
if exist ".venv\Scripts\python.exe" (
    set PY=.venv\Scripts\python.exe
    echo [量策] 使用虚拟环境 .venv
) else (
    where py >nul 2>nul && set PY=py -3
    if not defined PY (
        set PY=python
    )
    echo [量策] 未找到 .venv，使用系统 Python（%PY%）
)

REM 检查核心依赖（streamlit）是否可用，缺失则自动安装
%PY% -c "import streamlit" 2>nul || (
    echo [量策] 未检测到 streamlit，正在安装依赖...
    %PY% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [量策][错误] 依赖安装失败，请手动执行：
        echo   %PY% -m pip install -r requirements.txt
        pause
        exit /b 1
    )
)

REM 启动前自测门禁（离线、约 2 秒；失败仅告警，不阻断启动）
echo [量策] 正在运行离线自测验证（数据层 + 核心功能）...
%PY% run_selfcheck.py >nul 2>&1
if %errorlevel% equ 0 (
    echo [量策] 自测通过：数据层与核心功能正确性已验证。
) else (
    echo [量策][警告] 自测未完全通过，请运行 %PY% run_selfcheck.py 查看详情。
)

echo [量策] 正在启动服务 (http://localhost:%PORT%)...
start "" http://localhost:%PORT%
%PY% -m streamlit run app.py --server.port %PORT% --server.headless true --browser.gatherUsageStats false

endlocal
