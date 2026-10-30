#!/usr/bin/env bash
# Ejecutable único para Linux con PyInstaller -> dist/fruquis  (el de Windows se genera con build.bat en Windows)
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
uv pip install --python .venv/bin/python pyinstaller
ADD=""; [ -d fruquis/characters ] && ADD="--add-data fruquis/characters:fruquis/characters"
.venv/bin/python -m PyInstaller --noconfirm --onefile --name fruquis --icon fruquis/icon.png --add-data fruquis/icon.png:fruquis $ADD launcher.py
