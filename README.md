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
| 🪄 **Prompts listos** | ¿Falta una animación? Genera el prompt (plantilla con variables y fondo a elección) y la imagen de referencia para tu generador de imágenes. |

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

## 🔐 Seguridad del chat

- **Ideas** y **Estado** nunca ejecutan comandos.
- El **chat** puede usar Bash **solo si la casilla “Terminal” está activa** (visible en el compositor) y ejecuta sin pedir confirmación en tu carpeta personal. Desactívala si no la quieres.
- Necesita el CLI `claude` en el `PATH`.

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
