@echo off
chcp 65001 >nul
setlocal
rem Cria na area de trabalho o atalho "Pesquisa Nave" (abre o site da pesquisa de satisfacao
rem no navegador padrao, para o frequentador responder sozinho) e ja abre o site.
set "URL=https://pesquisas.navedoconhecimento.rio/"

for /f "delims=" %%d in ('powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"') do set "DESKTOP=%%d"
if not defined DESKTOP set "DESKTOP=%USERPROFILE%\Desktop"
for %%i in ("%~dp0..\web\icone.ico") do set "ICONE=%%~fi"
set "ATALHO=%DESKTOP%\Pesquisa Nave.url"

> "%ATALHO%" echo [InternetShortcut]
>> "%ATALHO%" echo URL=%URL%
if exist "%ICONE%" (
    >> "%ATALHO%" echo IconFile=%ICONE%
    >> "%ATALHO%" echo IconIndex=0
)
echo Atalho criado: %ATALHO%
if /i "%~1"=="--sem-abrir" exit /b 0
start "" "%URL%"
exit /b 0
