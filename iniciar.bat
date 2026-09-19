@echo off
rem Inicia a interface da staff (prepara o ambiente se for a primeira vez). E o alvo do atalho "Pesquisas Nave".
call "%~dp0setup\staff.bat" --sem-atalho %*
