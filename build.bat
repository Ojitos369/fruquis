@echo off
rem Fruquis - genera dist\fruquis.exe (un solo archivo, sin consola). Ejecutar en Windows.
cd /d "%~dp0"
call setup.bat || exit /b 1
uv pip install --python .venv\Scripts\python.exe pyinstaller || exit /b 1
set ADD=
if exist fruquis\characters set ADD=--add-data "fruquis\characters;fruquis\characters"
.venv\Scripts\python.exe -m PyInstaller --noconfirm --onefile --windowed --name fruquis %ADD% launcher.py
echo.
echo Listo: dist\fruquis.exe
