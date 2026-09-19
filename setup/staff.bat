@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

call :achar_python
if not defined PY (
    echo Python nao encontrado. Instalando pelo winget (pode pedir confirmacao)...
    winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
    call :achar_python
)
if not defined PY (
    echo.
    echo Nao consegui instalar o Python. Baixe em https://www.python.org/downloads/
    echo (marque "Add python.exe to PATH") e rode este script de novo.
    pause
    exit /b 1
)

%PY% setup\staff.py %*
if errorlevel 1 pause
exit /b %errorlevel%

:achar_python
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3" && goto :eof
python --version >nul 2>nul && set "PY=python" && goto :eof
for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%d\python.exe" set "PY="%%d\python.exe""
goto :eof
