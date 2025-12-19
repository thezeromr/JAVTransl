@echo off
setlocal
cd /d %~dp0

rem locate uv if already on PATH
set "UV_CMD="
where uv >nul 2>nul && set "UV_CMD=uv"

rem check default install path if not found
if not defined UV_CMD (
    set "UV_CMD=%USERPROFILE%\.local\bin\uv.exe"
    if not exist "%UV_CMD%" set "UV_CMD="
)

rem install uv when missing entirely
if not defined UV_CMD (
    echo [INFO] 未检测到 uv，正在安装...
    powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "Set-StrictMode -Version Latest; $ProgressPreference='SilentlyContinue'; irm https://astral.sh/uv/install.ps1 | iex"
    if exist "%USERPROFILE%\.local\bin\uv.exe" (
        set "UV_CMD=%USERPROFILE%\.local\bin\uv.exe"
    ) else (
        echo [ERROR] 无法安装或定位 uv，请检查网络或安装日志。
        goto :end
    )
)

if not defined UV_CMD (
    echo [ERROR] 未能定位 uv，请手动安装后重试。
    goto :end
)

echo [INFO] 已找到 uv：%UV_CMD%
"%UV_CMD%" run python main.py

:end
