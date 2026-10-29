@echo off
rem Fruquis con consola (para ver errores y usar los comandos list, check, prompt, add).
cd /d "%~dp0"
call setup.bat || exit /b 1
.venv\Scripts\python.exe -m fruquis %*
