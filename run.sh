#!/usr/bin/env bash
# Fruquis — arranque en Linux/macOS.  ./run.sh [run --scale 0.6 | list | check | prompt <anim> | add hoja.png ...]
set -euo pipefail
cd "$(dirname "$(readlink -f "$0" 2>/dev/null || echo "$0")")"
export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null 2>&1 || { echo "[fruquis] Falta uv: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2; exit 1; }
[ -x .venv/bin/python ] || { uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -r requirements.txt; }
exec .venv/bin/python -m fruquis "$@"
