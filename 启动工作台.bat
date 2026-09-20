@echo off
cd /d "%~dp0"
title bili-favlist 分类工作台（开发版）

echo ============================================
echo    bili-favlist 分类工作台（开发版）
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 找不到 .venv\Scripts\python.exe
    echo        请在项目目录下重建虚拟环境后重试。
    echo.
    pause
    exit /b 1
)

if exist "config.yaml" goto FORMAL
echo [提示] 未找到 config.yaml，将以【演示模式】启动。
echo        演示模式使用虚构示例数据，导出 / 写回不可用。
echo        正式使用：复制 config.example.yaml 为 config.yaml 并填入 Cookie。
echo.
goto RUN

:FORMAL
echo [信息] 已找到 config.yaml，正式模式启动。
echo.

:RUN
echo 启动后浏览器会自动打开 http://127.0.0.1:8787
echo 关闭本窗口即可停止服务。
echo.

".venv\Scripts\python.exe" src\main.py app

echo.
echo 服务已停止。
pause
