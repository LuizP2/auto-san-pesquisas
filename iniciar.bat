@echo off
rem Inicia a interface da staff (prepara o ambiente se for a primeira vez), sem precisar do Pesquisas Nave.exe.
call "%~dp0setup\staff.bat" --sem-exe %*
