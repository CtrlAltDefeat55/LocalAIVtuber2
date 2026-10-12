@echo off
setlocal
title Local AI VTuber
rem Works from the app folder, or from "Other start scripts" inside it.
cd /d "%~dp0"
if not exist "launcher\launcher.py" if exist "..\launcher\launcher.py" cd ..
set "ROOT=%CD%"

rem Everything stays inside this folder: Python, packages, models and caches.
set "UV=%ROOT%\runtime\uv\uv.exe"
set "UV_PYTHON_INSTALL_DIR=%ROOT%\runtime\python"
set "UV_CACHE_DIR=%ROOT%\cache\uv"
set "UV_NO_MODIFY_PATH=1"
set "UV_PYTHON_PREFERENCE=only-managed"

if exist "%UV%" goto run
echo First start: downloading the setup tool (uv, about 20 MB)...
if not exist "%ROOT%\runtime\uv" mkdir "%ROOT%\runtime\uv"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol='Tls12';" ^
  "$zip=Join-Path $env:TEMP 'lav-uv.zip';" ^
  "Invoke-WebRequest -UseBasicParsing 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' -OutFile $zip;" ^
  "Expand-Archive -Force $zip '%ROOT%\runtime\uv'; Remove-Item $zip"
if not exist "%UV%" (
  echo.
  echo Could not download uv. Check your internet connection and run "Start Windows.bat" again.
  echo If PowerShell is blocked on this PC, download uv-x86_64-pc-windows-msvc.zip from
  echo https://github.com/astral-sh/uv/releases and extract uv.exe into runtime\uv\
  pause
  exit /b 1
)

:run
"%UV%" run --no-project --python 3.11 "%ROOT%\launcher\launcher.py" --started-by "%~nx0" %*
if errorlevel 1 pause
endlocal
