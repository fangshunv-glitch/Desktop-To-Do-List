@echo off
chcp 65001 >nul
setlocal

echo ============================================
echo   今日事 TodayPlan - 一键打包
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 没找到 python，请先安装 Python 3.9+ 并勾选 "Add to PATH"
    pause
    exit /b 1
)

echo [1/3] 安装依赖...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)
python -m pip install pyinstaller

echo.
echo [2/3] 打包中（首次约 1-2 分钟）...
python -m PyInstaller --noconfirm --clean --windowed --onedir ^
    --name TodayPlan ^
    --icon icon.ico ^
    --distpath dist ^
    --workpath build ^
    --specpath build ^
    main.py
if errorlevel 1 (
    echo [错误] 打包失败，请查看上方日志
    pause
    exit /b 1
)

echo.
echo [3/3] 完成
echo   可执行文件： dist\TodayPlan\TodayPlan.exe
echo   直接双击即可运行；想放桌面就给它建个快捷方式。
echo.
pause
