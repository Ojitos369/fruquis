<div align="center">

# 🐙 Fruquis

### Mascotas de escritorio con vida propia

*Caminan, trepan, duermen, se dejan mimar… y te ayudan con tu trabajo.*

![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Qt](https://img.shields.io/badge/PySide6-Qt-41CD52?style=for-the-badge&logo=qt&logoColor=white)
![Linux](https://img.shields.io/badge/Linux-X11-FCC624?style=for-the-badge&logo=linux&logoColor=black)
![Windows](https://img.shields.io/badge/Windows-10%2B-0078D6?style=for-the-badge&logo=windows&logoColor=white)
![IA](https://img.shields.io/badge/IA-Claude-8A6AE0?style=for-the-badge)

**[Inicio rápido](#-inicio-rápido) · [Qué hace](#-qué-hace) · [Personajes](#-personajes) · [Comandos](#-comandos) · [Windows](#-windows)**

</div>

---

## ✨ Qué hace

| | |
|---|---|
| 🏃 **Vive en tu pantalla** | Camina por el piso, **trepa las paredes**, camina por el **techo** y se suelta. Salta al borde de tu ventana activa y, si es una terminal, "teclea". |
| 🤾 **Se lanza con físicas** | Agárrala, arrástrala y suéltala con impulso: sigue el tiro, **se pega a la pared o al techo** donde pegue y corre un poco al aterrizar. |
| 💜 **Tamagotchi** | Hambre, limpieza, diversión y energía. **Comer · Limpiar · Jugar · Dormir · Mimar**. Se acuerda de ti aunque cierres días. |
| 💬 **Chat con IA** | Botón flotante que **arrastras a donde quieras**. Respuestas que se escriben en vivo, markdown, copiar, regenerar, detener. Puede **ejecutar comandos** si lo permites. |
| 💡 **Ideas según tu ventana** | Un clic y te sugiere qué hacer según lo que tienes abierto. |
| 🎞️ **Animaciones a tu medida** | Importa hojas de sprites de **cualquier tamaño**: la IA detecta los cuadros, los limpia, los nombra y elige fps y modo. |
| 🧩 **Muchos personajes** | Cada mascota es un *personaje* con sus hojas y su historia. Crea, cambia y **llévalos entre equipos en un .zip**. |
| 🪄 **Prompts listos** | ¿Falta una animación? Genera el prompt (plantilla con variables y fondo a elección), o un **prompt general** para todas las que faltan (cada una como imagen separada, respetando las variables de cada una). |
| ⚡ **Genera varias a la vez** | En el catálogo → *Generar varias…*: marca faltantes y/o animaciones a reemplazar y se generan **en paralelo y en segundo plano** (la mascota avisa al terminar). Revisa una por una o aplica todas las listas. |
| ⚙️ **Ajustes** | Binarios del chat (`claude`) y del generador (`codex`) con detectar/probar, tamaño de la mascota, generaciones en paralelo, fondo de los prompts y valores del chat. |
| 🧬 **Identidad y anatomía** | La IA mira al personaje y escribe cómo es y qué cuerpo tiene (una serpiente repta, un pulpo usa tentáculos, sin brazos saluda con la cola). Se incluye en **todos** los prompts y adapta cada animación a su anatomía; es editable. |
| 🔒 **Siempre fiel al personaje** | Cada generación lleva adjuntas la **hoja neutral** y la imagen general (si no hay hoja, se crea antes), con instrucciones explícitas; la IA verifica que el resultado sea el mismo personaje y reintenta si no. |
| 🧼 **Cuadros limpios** | Cada pieza de la hoja se asigna a un solo cuadro (no se corta con líneas rectas) y la IA revisa pieza por pieza lo dudoso: ya no se cuelan pedazos del cuadro vecino. |
| 🔁 **Mejora con chat** | ¿El reverso salió mal o no se distingue? Describe qué corregir y se genera una **nueva versión** a partir de la actual; itera las veces que haga falta, vuelve a una versión anterior y quédate con la mejor (hoja neutral o cualquier animación). |
| 💬 **Chat flotante** | Doble clic en la mascota (o menú → *Chat flotante*): una ventanita junto a ella que la sigue. Mientras responde **se queda quieta** y muestra lo que hace: pensando, leyendo, trabajando, escribiendo. |
| 👁️ **Ve y controla el escritorio** | Con *Ver ventana* el chat recibe una captura de tu ventana activa; con *Controlar* (desactivado por defecto) puede mover el ratón, hacer clic, teclear y cambiar de ventana. Cada acción queda en `~/.fruquis/ctl.log`. |
| ✨ **Genera con ChatGPT** | Un clic pasa el prompt a **ChatGPT vía Codex CLI** y recoge la imagen para armar la animación. Usa la **hoja neutral** (4 vistas) como referencia para mantener todos los detalles; si no existe, la crea primero. |

---

## 🚀 Inicio rápido

### Linux

```bash
sudo apt install libxcb-cursor0        # requisito de Qt (una vez)
./run.sh                               # crea el entorno la primera vez y arranca
```

### Windows

Doble clic en **`fruquis.vbs`** → arranca **sin terminal**. La primera vez abre una ventana para instalar el entorno (requiere [uv](https://docs.astral.sh/uv/)).

> Los personajes **no vienen en el repositorio**. En una instalación nueva, Fruquis te pide un `.zip` de personaje al abrir (ver [Personajes](#-personajes)).

---

## 🧸 Personajes

> Todo vive en **una sola ventana** con vistas (Chat · Cuidar · Personajes · Catálogo · Prompt). Se navega como en un navegador: **Esc**, **Alt+←**, el botón **←** o el botón atrás del ratón regresan a la vista anterior; en la primera, Esc cierra la ventana.

Un personaje es una carpeta con su `character.json`, sus hojas de sprites y una descripción. Viven en `~/.fruquis/characters/`.

**Llevarlos a otro equipo**

1. En el equipo de origen: clic en la mascota → **Personajes…** → **Exportar personaje (.zip)…**
2. Copia el `.zip` (USB, nube, lo que prefieras).
3. En el destino: **Personajes…** → **Importar personaje (.zip)…**

Si el id ya existe se importa con sufijo (`-2`, `-3`…) para no pisar nada. El import **valida** el zip antes de escribir: rutas seguras, solo `.json`, `.png` y `.md`, tamaños acotados e imágenes reales.

**Consistencia: imagen general y hoja neutral**

- **Imagen general:** una imagen de referencia del personaje que cargas tú (Personajes → *Imagen general y hoja neutral*, o al crear el personaje).
- **Hoja neutral:** 4 vistas (frontal, trasera, lateral izquierda y lateral derecha) respetando todos los detalles. Se **genera con ChatGPT** a partir de la imagen general o la cargas propia. Es solo de referencia: no aparece en el catálogo de animaciones.
- Al generar cualquier animación se adjunta la hoja neutral; si falta, **se crea primero** automáticamente. El resultado se recorta (fondo `#FF00FF`), se divide en cuadros y pasa por una pantalla de revisión antes de aplicarse.
- Requiere [Codex CLI](https://github.com/openai/codex) con sesión de ChatGPT (`codex login`). La pantalla lo comprueba.

**Agregar animaciones**

- Menú → **Personajes… → Catálogo de animaciones…**: vista previa animada, ajustar fps y modo, **probar en la mascota**, **reemplazar**, **eliminar** o agregar las que faltan.
- **Agregar hoja de sprites…** acepta cualquier tamaño y distribución. La IA (`haiku`, esfuerzo medio) dice qué animaciones hay y si varias filas son una sola; tú confirmas o corriges.

<details>
<summary><b>🎬 Animaciones que conoce</b></summary>

`idle` · `running-right` · `running-left` · `jumping` · `waving` · `failed` · `waiting` · `review` · `talking` · `sleeping` · `sitting` · `dragged` · `falling` · `climbing` · `poking` · `typing` · `playing` · `eating` · `cleaning` · `pampered` · `look` (16 cuadros, sigue el cursor)

Las que falten usan una **animación de respaldo** (por ejemplo `sleeping` → `waiting`). `climbing` se dibuja de pie y la app la rota sobre paredes y techo.

</details>

---

## 🛠️ Comandos

```bash
./run.sh                                   # iniciar
./run.sh list                              # ver personajes
./run.sh check [--character id]            # qué animaciones faltan
./run.sh prompt sleeping --background "#FF00FF"   # prompt para generar una animación
./run.sh add hoja.png                      # agregar hoja (la IA nombra las animaciones)
./run.sh add hoja.png --names a,b --no-ai  # nombrarlas tú, una por fila
./run.sh source imagen.png                 # imagen general del personaje
./run.sh neutral --generate                # hoja neutral con ChatGPT (o --file hoja.png)
./run.sh generate sleeping                 # genera una animación con ChatGPT y la agrega
./run.sh codex                             # comprobar Codex CLI
./run.sh export [id] --out personaje.zip   # exportar un personaje
./run.sh import personaje.zip [--overwrite]
```

En Windows usa `run.bat` con los mismos argumentos.

---

## 🪟 Windows

| Archivo | Para qué |
|---|---|
| `fruquis.vbs` | Doble clic: arranca **sin terminal**. |
| `run.bat` | Con consola, para errores y los comandos de arriba. |
| `setup.bat` | Crea el entorno (lo llaman los demás). |
| `build.bat` | Genera `dist\fruquis.exe` (un solo archivo, sin consola). **Ejecútalo en Windows.** |

En el `.exe` los comandos de consola no imprimen nada; úsalos con `run.bat`.

Para Linux, `./build.sh` genera `dist/fruquis`.

---

## 🖥️ Linux, Windows y macOS

Los binarios (`claude` para el chat, `codex` para generar imágenes) se buscan en este orden: la ruta elegida en **Ajustes**, `CLAUDE_BIN` / `CODEX_BIN`, el PATH, los lugares habituales de cada sistema (npm, Homebrew, nvm, volta, scoop, WinGet…) y, en macOS/Linux, el PATH de tu shell de login (para cuando la app se abre con doble clic). En Windows los atajos `.cmd` de npm se ejecutan directo con `node`, y los prompts viajan por la entrada estándar para que `cmd.exe` no rompa comillas ni saltos de línea. Pruebas: `.venv/bin/python tests/test_binaries.py` (simula los tres sistemas).

Ver y controlar el escritorio: en macOS hay que conceder *Accesibilidad* y *Grabación de pantalla*; en Linux funciona con X11 (en Wayland puede no funcionar).

---

## 🔐 Seguridad del chat

- **Ideas** y **Estado** nunca ejecutan comandos.
- El **chat** puede usar Bash **solo si la casilla “Terminal” está activa** (visible en el compositor) y ejecuta sin pedir confirmación en tu carpeta personal. Desactívala si no la quieres.
- **Controlar el escritorio** está desactivado por defecto; se activa con su casilla en el chat o en Ajustes. Límite de 60 acciones por minuto y confirmación pedida antes de acciones destructivas.
- Necesita el CLI `claude` (ruta configurable en Ajustes).

---

## 🧱 Estructura

```
fruquis/            paquete: app, chat, sprites, importer, care, ui…
  characters/       personajes locales (ignorado por git)
launcher.py         punto de entrada para PyInstaller
run.sh · run.bat · fruquis.vbs · setup.bat · build.sh · build.bat
```

Tus datos (personajes del usuario, estado del tamagotchi, preferencias) están en `~/.fruquis/`.

<div align="center">

*Hecho con 💜 y un pulpito cian.*

</div>
