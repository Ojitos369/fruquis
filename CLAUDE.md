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
- Controlar el equipo: `control.py` (capturas + ratón/teclado, casilla «Controlar») ↔ `PhoneService.kt` (servicio de accesibilidad: lee el árbol de la pantalla, no capturas; la IA responde un paso JSON a la vez; casilla «Controlar el teléfono», prefs "app" → `control`; lo usan el chat y `VoiceService`).
- Solo escritorio (no aplica a Android): ventanas (`winctx.py`) y casilla «Navegador» (`chat.ask` lanza el CLI con `--chrome`, sin `--strict-mcp-config`, que bloquea la extensión).
- Ubicación aproximada (por IP, se añade al prompt de sistema del chat): `fruquis/place.py` ↔ `Place` en `Ai.kt`.
- Asistente por voz (nombre del personaje + orden, «detener», cambio de personaje): `fruquis/voice.py` (Whisper local) y `chatui.pick_character` ↔ `VoiceService.kt` (reconocedor del sistema; mismos criterios de nombre y de alto). En Android la escucha activa se enciende con el mosaico de ajustes rápidos `ListenTile.kt` (pasa por `AssistActivity` para arrancar al frente), y el botón del asistente (`AssistActivity`) dicta una orden suelta. En escritorio todo lo oído y respondido se registra en `~/.fruquis/voice.log` (JSON por línea: `oido`, `pedido`, `respuesta`, `detenido`…): revísalo al depurar la voz. Android guarda el mismo formato en `files/voice.log` (`VoiceLog` en `VoiceService.kt`, más `paso`/`resultado` de `PhoneService`): `adb shell run-as com.ojitos369.fruquis cat files/voice.log`.
- Globos de diálogo y de pensamiento junto a la mascota: `Bubble` en `fruquis/app.py` ↔ `BubbleView` en `OverlayService.kt` (acción `SAY`, `OverlayService.bubble`; sin mascota flotando, Toast). Las respuestas del chat con el chat cerrado salen en globo en ambas.
- Solo Android: botón del asistente del sistema (`AssistActivity.kt`, filtro `ASSIST`; elegir Fruquis como «App de asistente digital») → dicta y manda `VoiceService.ASK`.
- Personalidad del personaje (`personality`/`story` en `character.json`; vacía = «tierna») y animación pedida por la IA (marca `[[anim:nombre]]` al final de la respuesta, se quita del texto y la mascota la hace; si es de cuidado aplica su efecto): `chat.persona_prompt`/`split_anim` + `Pet.act_pending` (`app.py`) y `fruquis/personality.py` (buscar en la red / sacar de la historia, en `ProfileView`) ↔ `Persona` en `Ai.kt` (lo usan el chat y `VoiceService`; `EditCharDialog`). Con `PhoneService` no se pide la marca (responde JSON).
- Voz de las respuestas: género del personaje (`gender` en `character.json`: "masculino", "femenino" o vacío = voz del sistema; `ProfileView` ↔ `EditCharDialog`) y ajuste «Responder con voz» (store/prefs "app" → `speak`, por defecto sí): `fruquis/speech.py` (spd-say/espeak-ng, `say`, System.Speech; lo usa `chatui.got`, «detener» lo calla) ↔ `Speech` en `VoiceService.kt` (TextToSpeech; Android no da el género de las voces: lo busca en nombre/características y si no, cambia el tono). Lo usan el chat y `VoiceService`.
- Importar personajes (.zip con `<id>/character.json` + .png/.md): `sprites.py` ↔ `MainActivity.importZip`.

## Convenciones

- Escritorio: `fruquis/store.py` guarda en `~/.fruquis`; prueba rápida `.venv/bin/python -m fruquis.care` y `tests/`.
- Android: Kotlin (plugin `org.jetbrains.kotlin.android`, código en `android/app/src/main/kotlin`). La interfaz principal es Jetpack Compose (Material 3, `MainActivity.kt`); la mascota flotante (`OverlayService.kt`) usa una `View` dentro de una ventana superpuesta a propósito (Compose ahí necesita dueños de ciclo de vida). Más librerías se añaden en `app/build.gradle`. `minSdk 26`.
- Los personajes no se versionan (`fruquis/characters/`, `*.zip`).
- Comentarios y textos de UI en español.
