@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")
set "VPY=.venv\Scripts\python.exe"
set PLAYWRIGHT_BROWSERS_PATH=0

if not exist "%VPY%" (
    echo Preparando o ambiente pela primeira vez (Python + Chromium, ~150 MB) ...
    %PY% -m venv .venv || goto :erro
    "%VPY%" -m pip install --upgrade pip playwright || goto :erro
    "%VPY%" -m playwright install chromium || goto :erro
)

"%VPY%" servidor.py
exit /b %errorlevel%

:erro
echo.
echo Algo deu errado - veja a mensagem acima.
pause
exit /b 1
