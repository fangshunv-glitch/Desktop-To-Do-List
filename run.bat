@echo off
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 没找到 python，请先安装 Python 3.9+ 并勾选 "Add to PATH"
    pause
    exit /b 1
)

python -c "import PySide6" >nul 2>nul
if errorlevel 1 (
    echo 首次运行，正在安装 PySide6 ...
    python -m pip install -r requirements.txt
)

start "" pythonw main.py
