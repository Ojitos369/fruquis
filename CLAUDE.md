# Fruquis — guía para Claude

Fruquis existe en **dos apps** que deben mantenerse en paridad:

| App | Código | Cómo se genera |
|---|---|---|
| Escritorio (Python + PySide6: Linux, Windows, macOS) | `fruquis/`, `launcher.py` | `./run.sh`, `build.sh`, `build.bat` |
| Android (Kotlin) | `android/` | `gradle -p android assembleDebug` → `android/app/build/outputs/apk/debug/app-debug.apk`; también el workflow `.github/workflows/android.yml` (artefacto `fruquis-apk`) |

## Regla principal

**Todo cambio debe hacerse para la app de escritorio Y para la de Android.** Antes de dar una tarea por terminada:

1. Si el cambio toca algo que existe en ambas (mascota, animaciones/sprites, formato de personaje `character.json`/.zip, tamagotchi, textos, valores), aplícalo en las dos.
2. Si algo no aplica a una plataforma (p. ej. caminar por ventanas, controlar el escritorio, CLI `claude`/`codex`, que son solo de escritorio), dilo explícitamente en la respuesta en vez de omitirlo en silencio.
3. Si se cambia el formato de datos (`character.json`, zip de personajes, `care.json`), ambas apps deben seguir leyendo el mismo formato.

## Puntos de paridad

- Tamagotchi: `fruquis/care.py` ↔ `Care.kt` (`DECAY`, `FLOOR`, `ACTIONS`).
- Hojas de sprites y animaciones de respaldo: `fruquis/sprites.py` (`WANTED`) y `fruquis/app.py` ↔ `Sprite.kt` (`FALLBACK`) y el `Canvas` de `MainActivity.kt`.
- Mascota flotante: `fruquis/app.py` (caminar, trepar, lanzar, caer) ↔ `OverlayService.kt` (ventana superpuesta + servicio en primer plano; `Sprite.kt` es el lector de hojas compartido). Estados y animaciones deben coincidir.
- IA (binario o API, oficial o propia): `fruquis/provider.py` ↔ `Ai.kt` (valores por defecto, rutas y formato de ajustes). En escritorio todo uso de IA pasa por `provider` (`api_text`, `api_image`, `vision`); no llames a `claude`/`codex` directo desde código nuevo. Android solo tiene API (sin binarios).
- Importar personajes (.zip con `<id>/character.json` + .png/.md): `sprites.py` ↔ `MainActivity.importZip`.

## Convenciones

- Escritorio: `fruquis/store.py` guarda en `~/.fruquis`; prueba rápida `.venv/bin/python -m fruquis.care` y `tests/`.
- Android: Kotlin (plugin `org.jetbrains.kotlin.android`, código en `android/app/src/main/kotlin`). La interfaz principal es Jetpack Compose (Material 3, `MainActivity.kt`); la mascota flotante (`OverlayService.kt`) usa una `View` dentro de una ventana superpuesta a propósito (Compose ahí necesita dueños de ciclo de vida). Más librerías se añaden en `app/build.gradle`. `minSdk 26`.
- Los personajes no se versionan (`fruquis/characters/`, `*.zip`).
- Comentarios y textos de UI en español.
