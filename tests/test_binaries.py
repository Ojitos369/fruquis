"""Pruebas de los binarios (`python tests/test_binaries.py`): resolución de rutas por sistema, atajos .cmd de npm en Windows y el chat con un
`claude` simulado (streaming, fases, prompt de sistema en archivo, prompt por stdin). Se simulan Windows y macOS desde Linux."""
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
tmp = Path(tempfile.mkdtemp())
os.environ["HOME"] = str(tmp / "home")
os.environ["USERPROFILE"] = os.environ["HOME"]
os.environ["APPDATA"], os.environ["LOCALAPPDATA"] = str(tmp / "AppData/Roaming"), str(tmp / "AppData/Local")
for k in ("CLAUDE_BIN", "CODEX_BIN"):
    os.environ.pop(k, None)

from fruquis import binaries as b  # noqa: E402

home = Path(os.environ["HOME"])

# 1) rutas habituales por sistema
win = {str(p) for p in b.candidates("claude", win=True)}
assert str(tmp / "AppData/Roaming/npm/claude.cmd") in win and str(home / ".local/bin/claude.exe") in win, win
assert all(p.endswith((".exe", ".cmd")) for p in win)
mac = {str(p) for p in b.candidates("codex", win=False, mac=True)}
assert "/opt/homebrew/bin/codex" in mac and str(home / ".local/bin/codex") in mac and str(home / "Library/pnpm/codex") in mac
lin = {str(p) for p in b.candidates("codex", win=False, mac=False)}
assert "/opt/homebrew/bin/codex" not in lin and "/snap/bin/codex" in lin and "/usr/local/bin/codex" in lin
print("rutas por sistema ✓")

# 2) atajo .cmd de npm → node + script (sin cmd.exe, que rompe comillas y saltos de línea)
shim = '@ECHO off\nGOTO start\n:start\nSETLOCAL\nSET dp0=%~dp0\n"%_prog%"  "%dp0%\\node_modules\\@openai\\codex\\bin\\codex.js" %*\n'
d = tmp / "npm"
d.mkdir()
(d / "codex.cmd").write_text(shim)
got = b.argv(str(d / "codex.cmd"), win=True)
assert got[0].endswith(("node", "node.exe")) or got[0] == "cmd.exe", got
(d / "node.exe").write_text("")  # node junto al atajo (instalaciones de nvm-windows / Node portable)
got = b.argv(str(d / "codex.cmd"), win=True)
assert got == [str(d / "node.exe"), str(d / "node_modules/@openai/codex/bin/codex.js")], got
(d / "raro.cmd").write_text("@echo off\nraro.exe %*\n")
assert b.argv(str(d / "raro.cmd"), win=True) == ["cmd.exe", "/d", "/s", "/c", str(d / "raro.cmd")]  # sin script js: respaldo por cmd.exe
assert b.argv("/usr/bin/x", win=True) == ["/usr/bin/x"] and b.argv(str(d / "codex.cmd"), win=False) == [str(d / "codex.cmd")]
print("atajos .cmd ✓")

# 3) detección por PATH y por variable de entorno; la ruta de Ajustes manda
fake = tmp / "fakebin"
fake.mkdir()
exe = fake / "claude"
exe.write_text("#!/usr/bin/env python3\nprint('claude fake 9.9')\n")
exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
os.environ["PATH"] = str(fake) + os.pathsep + os.environ["PATH"]
assert b.detect("claude") == str(exe)
os.environ["CLAUDE_BIN"] = str(exe)
assert b.detect("claude") == str(exe)
from fruquis import store  # noqa: E402
other = fake / "otro"
other.write_text("#!/bin/sh\necho otro\n")
other.chmod(other.stat().st_mode | stat.S_IEXEC)
store.put("bin_claude", str(other))
assert b.resolve("claude") == str(other)
store.put("bin_claude", "/no/existe")
assert b.resolve("claude") == str(exe)  # una ruta inválida en Ajustes se ignora
store.put("bin_claude", "")
assert b.check(str(exe)) == (True, "claude fake 9.9") and b.check("/no/existe")[0] is False
print("detección y ajustes ✓")

# 4) chat con un claude simulado: streaming, fases, prompt de sistema en archivo (no en argumentos), prompt por stdin
fake_claude = fake / "claude"
fake_claude.write_text('''#!/usr/bin/env python3
import sys, json
a = sys.argv[1:]
if a == ["--version"]:
    print("claude fake 9.9"); sys.exit(0)
sysfile = a[a.index("--system-prompt-file") + 1]
assert "--system-prompt" not in a and "--output-format" in a, a
sys_txt = open(sysfile, encoding="utf-8").read()
prompt = sys.stdin.read()
def out(o): print(json.dumps(o), flush=True)
out({"type": "system", "subtype": "init"})
out({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": ""}]}})
if "--tools" in a and "Read" in a[a.index("--tools") + 1]:
    out({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read", "input": {}}]}})
out({"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}})
out({"type": "result", "result": "persona=%s|bash=%s|ctl=%s|prompt=%s" % ("Ayax" in sys_txt, "Bash" in sys_txt, "screenshot" in sys_txt, prompt.strip()[:40])})
''')
fake_claude.chmod(fake_claude.stat().st_mode | stat.S_IEXEC)
from fruquis import chat  # noqa: E402
phases = []
r = chat.ask('Hola "mundo" & más\ncon salto', persona=("Ayax", "una serpiente"), on_phase=phases.append)
assert r.startswith("persona=True|bash=False|ctl=False|prompt=Hola \"mundo\" & más"), r
assert phases[0] == "thinking" and phases[-1] == "writing" and "reading" not in phases, phases
phases.clear()
r = chat.ask("mira", persona=("Ayax", "x"), image="/tmp/x.png", desktop=True, on_phase=phases.append)
assert "ctl=True" in r and "bash=True" in r, r
assert phases == ["thinking", "thinking", "reading", "writing"], phases
print("chat (streaming, fases, stdin, archivo de sistema) ✓")
print("TODO OK")
