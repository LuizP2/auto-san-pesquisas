@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

call :achar_python
if defined PY goto :rodar

echo Python nao encontrado. Instalando pelo winget - pode pedir confirmacao...
winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
call :achar_python
if defined PY goto :rodar

echo.
echo Nao consegui instalar o Python. Baixe em https://www.python.org/downloads/
echo marque "Add python.exe to PATH" na instalacao e rode este script de novo.
pause
exit /b 1

:rodar
%PY% setup\staff.py %*
set "CODIGO=%errorlevel%"
if not "%CODIGO%"=="0" pause
exit /b %CODIGO%

:achar_python
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3" && goto :eof
python --version >nul 2>nul && set "PY=python" && goto :eof
for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%d\python.exe" set "PY="%%d\python.exe""
goto :eof
