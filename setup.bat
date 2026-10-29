@echo off
rem Fruquis - crea el entorno la primera vez (ventana visible para ver el progreso).
cd /d "%~dp0"
where uv >nul 2>nul || (echo [fruquis] Falta uv: https://docs.astral.sh/uv/getting-started/installation/ & pause & exit /b 1)
if not exist .venv\Scripts\python.exe (
  uv venv .venv --python 3.12 && uv pip install --python .venv\Scripts\python.exe -r requirements.txt
  if errorlevel 1 (echo [fruquis] Fallo la instalacion & pause & exit /b 1)
)
