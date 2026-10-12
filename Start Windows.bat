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

rem A missing, half-downloaded or damaged uv is detected here and fetched again.
if exist "%UV%" "%UV%" --version >nul 2>&1 && goto run
if exist "%UV%" echo The setup tool (uv) is damaged - downloading it again...
if not exist "%UV%" echo First start: downloading the setup tool (uv, about 20 MB)...
if not exist "%ROOT%\runtime\uv" mkdir "%ROOT%\runtime\uv"
set "UVTRY=0"
:getuv
set /a UVTRY+=1
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol='Tls12';" ^
  "$zip='%ROOT%\runtime\uv\uv-download.zip'; $tmp='%ROOT%\runtime\uv\unpack';" ^
  "Invoke-WebRequest -UseBasicParsing 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' -OutFile $zip;" ^
  "if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }; Expand-Archive -Force $zip $tmp;" ^
  "Get-ChildItem $tmp -Recurse -Filter *.exe | ForEach-Object { Move-Item -Force $_.FullName '%ROOT%\runtime\uv\' };" ^
  "Remove-Item -Recurse -Force $tmp, $zip"
if exist "%UV%" "%UV%" --version >nul 2>&1 && goto run
if %UVTRY% LSS 3 (
  echo Download failed, retrying in 5 seconds...
  timeout /t 5 /nobreak >nul
  goto getuv
)
rem Still no working uv after 3 tries.
(
  echo.
  echo Could not download uv. Check your internet connection and run "Start Windows.bat" again.
  echo If PowerShell is blocked on this PC, download uv-x86_64-pc-windows-msvc.zip from
  echo https://github.com/astral-sh/uv/releases and extract uv.exe into runtime\uv\
  pause
  exit /b 1
)

:run
rem Reinstall the private Python if it is missing or damaged (the launcher runs on it).
"%UV%" run --no-project --python 3.11 python -c "import encodings, json, zipfile, ssl" >nul 2>&1 || "%UV%" python install --reinstall 3.11
"%UV%" run --no-project --python 3.11 "%ROOT%\launcher\launcher.py" --started-by "%~nx0" %*
if errorlevel 1 pause
endlocal
