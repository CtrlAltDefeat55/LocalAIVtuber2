@echo off
setlocal
title Local AI VTuber
cd /d "%~dp0"

rem Everything stays inside this folder: Python, packages, models and caches.
set "UV=%~dp0runtime\uv\uv.exe"
set "UV_PYTHON_INSTALL_DIR=%~dp0runtime\python"
set "UV_CACHE_DIR=%~dp0cache\uv"
set "UV_NO_MODIFY_PATH=1"
set "UV_PYTHON_PREFERENCE=only-managed"

if exist "%UV%" goto run
echo First start: downloading the setup tool (uv, about 20 MB)...
if not exist "%~dp0runtime\uv" mkdir "%~dp0runtime\uv"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol='Tls12';" ^
  "$zip=Join-Path $env:TEMP 'lav-uv.zip';" ^
  "Invoke-WebRequest -UseBasicParsing 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' -OutFile $zip;" ^
  "Expand-Archive -Force $zip '%~dp0runtime\uv'; Remove-Item $zip"
if not exist "%UV%" (
  echo.
  echo Could not download uv. Check your internet connection and run start.bat again.
  pause
  exit /b 1
)

:run
"%UV%" run --no-project --python 3.11 "%~dp0launcher\launcher.py" %*
if errorlevel 1 pause
endlocal
