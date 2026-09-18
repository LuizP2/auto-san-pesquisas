@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ==========================================
echo  Pesquisas Nave - gerar o executavel
echo ==========================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")
set "VPY=.venv\Scripts\python.exe"

if not exist "%VPY%" (
    echo [1/5] Criando o ambiente Python em .venv ...
    %PY% -m venv .venv || goto :erro
) else (
    echo [1/5] Ambiente .venv ja existe.
)

echo [2/5] Instalando dependencias (playwright, pyinstaller) ...
"%VPY%" -m pip install --upgrade pip playwright pyinstaller || goto :erro

echo [3/5] Baixando o Chromium para dentro do pacote (~150 MB, so na primeira vez) ...
set PLAYWRIGHT_BROWSERS_PATH=0
"%VPY%" -m playwright install chromium || goto :erro

echo [4/5] Gerando dist\PesquisasNave\PesquisasNave.exe (leva alguns minutos) ...
"%VPY%" -m PyInstaller --noconfirm --log-level WARN pesquisas.spec || goto :erro

echo [5/5] Criando o atalho "Pesquisas Nave" na area de trabalho ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0criar_atalho.ps1" || goto :erro

echo.
echo Pronto! Use o atalho "Pesquisas Nave" na area de trabalho.
echo O programa esta em: %~dp0dist\PesquisasNave\PesquisasNave.exe
echo (config.json, contas.json e as capturas ficam nessa mesma pasta.)
echo.
pause
exit /b 0

:erro
echo.
echo Algo deu errado - veja a mensagem acima.
echo Se preferir nao compilar, use iniciar.bat (ele roda direto pelo Python).
echo.
pause
exit /b 1
