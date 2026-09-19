@echo off
REM ============================================================================
REM scripts\setup_venv.bat  ——  从 Jenkinsfile Stage 1.1 抽出
REM 环境变量由 Jenkins environment{} 注入: CI_ROOT, VENV_PY
REM ============================================================================
setlocal
cd /d "%CI_ROOT%"

if not exist ".venv\Scripts\python.exe" (
    echo [venv] Creating virtual environment...
    python -m venv .venv
) else (
    echo [venv] Reusing existing virtual environment
)

echo [venv] Installing dependencies (with pip retry)...
"%VENV_PY%" -m pip install --quiet --retries 5 --timeout 60 -r requirements.txt
if errorlevel 1 (
    echo [venv] pip install failed on first try, retrying after 10s...
    REM 规则16: 不用 ping 当 sleep —— 这里用 timeout 命令（Windows 原生）
    timeout /t 10 /nobreak >nul
    "%VENV_PY%" -m pip install --quiet --retries 5 --timeout 60 -r requirements.txt
    if errorlevel 1 (
        echo [venv] pip install FAILED after retry
        exit /b 1
    )
)

echo [venv] Setup complete
"%VENV_PY%" --version
endlocal
