@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ==========================================
echo  Pesquisas Nave - gerar o executavel
echo ==========================================
echo.

echo [1/2] Ambiente Python + Playwright + Chromium - via setup\staff.bat ...
call "%~dp0setup\staff.bat" --so-instalar || goto :erro
set "VPY=.venv\Scripts\python.exe"

echo.
echo [2/2] Gerando dist\PesquisasNave\PesquisasNave.exe - leva alguns minutos ...
"%VPY%" -m pip install --disable-pip-version-check pyinstaller || goto :erro
"%VPY%" -m PyInstaller --noconfirm --log-level WARN pesquisas.spec || goto :erro

echo.
echo Pronto! O programa completo esta em: %~dp0dist\PesquisasNave\PesquisasNave.exe
echo config.json, contas.json e as capturas ficam nessa mesma pasta.
echo.
pause
exit /b 0

:erro
echo.
echo Algo deu errado - copie a mensagem acima para pedir ajuda.
echo Sem compilar, setup\staff.bat faz o mesmo rodando direto pelo Python.
echo.
pause
exit /b 1
