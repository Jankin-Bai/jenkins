@echo off
REM ============================================================================
REM scripts\build_app.bat  ——  从 Jenkinsfile Stage 2.2 抽出
REM 环境变量: APP_GCC, APP_SDK, VENV_PY, TOOLS, CI_ROOT, DRY_RUN
REM 退出码: 0=成功  1=失败且无 prebuilt  2=失败但已有 prebuilt
REM ============================================================================
setlocal EnableDelayedExpansion
cd /d "%APP_GCC%"

if /I "%DRY_RUN%"=="true" (
    echo [build-app][DRY-RUN] would: make SDK_ROOT=%APP_SDK% clean && make
    exit /b 0
)

echo [build-app] Cleaning...
mingw32-make SDK_ROOT="%APP_SDK%" V=1 clean 2>&1

echo [build-app] Compiling (attempt 1)...
mingw32-make SDK_ROOT="%APP_SDK%" V=1 2>&1
if exist "out\lst\ble_app_uart_c.elf" goto build_ok

echo [WARN] Link failed on attempt 1. Retrying with response file...
if not exist "out\obj" goto build_fail
dir /b /s /o-d "out\obj\*.o" > obj_list.txt
echo [build-app] Linking (attempt 2 with response file)...
mingw32-make SDK_ROOT="%APP_SDK%" V=1 OBJ_ADJUST="@obj_list.txt" 2>&1
if exist "out\lst\ble_app_uart_c.elf" goto build_ok
goto build_fail

:build_ok
echo [build-app] Generating .bin...
if not exist "out\ble_app_uart_c.bin" goto build_fail
echo [PASS] app compiled: out\ble_app_uart_c.bin
exit /b 0

:build_fail
echo [WARN] App build failed.
if exist "%CI_ROOT%\app_fw.bin" (
    echo [INFO] Existing app_fw.bin found (pre-built)
    exit /b 2
) else (
    echo [FAIL] App build failed and no existing app_fw.bin found
    exit /b 1
)
endlocal
