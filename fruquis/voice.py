"""Asistente por voz: escucha en segundo plano (sin enviar audio a ningún lado: Whisper local) y, al oír el nombre del personaje, toma lo que
sigue como pedido: «Fruquis, abre el navegador» o «Fruquis» (te escucho…) y luego la orden. Whisper recibe el nombre como texto guía
(initial_prompt), así que escribe bien nombres que no son palabras del español (Mively, Mutama…): con un reconocedor de vocabulario fijo no
salían. Paridad con Android (VoiceService.kt, mismo criterio de nombre). Dependencias opcionales: `pip install faster-whisper sounddevice`; el
modelo (~145 MB) se baja una vez a ~/.fruquis al activarlo."""
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from contextlib import contextmanager
from difflib import SequenceMatcher
from queue import Empty, Queue

from PySide6.QtCore import QObject, Signal

from . import deps, machine, speech, store

MODEL_URL = "https://huggingface.co/Systran/faster-whisper-{}/resolve/main/"
MODELS = {"base": 145_000_000, "small": 483_000_000}  # tamaño de model.bin: «small» entiende bastante mejor el español
MODEL_FILES = {("config.json",): 2_400, ("vocabulary.txt", "vocabulary.json"): 460_000, ("tokenizer.json",): 2_200_000}  # archivos (con nombres alternativos) y bytes aproximados, para el %
LOG = store.HOME / "voice.log"
_log_lock = threading.Lock()
AWAKE_S = 8  # tras decir solo el nombre, tiempo para dictar la orden
LOW_CONF = -1.0  # confianza media (logprob) por debajo de la cual no se ejecuta lo entendido: «Más de un máximo descrito, yo» era «muéstrame el escritorio»
RATE, BLOCK = 16000, 1600  # 100 ms por bloque
END_MS, MAX_S, MIN_MS = 700, 15, 300  # silencio que cierra la frase, frase máxima y voz mínima para transcribir


def log(evento: str, **datos):
    """Registro de lo que oye el asistente y de lo que responde, para revisarlo después: una línea JSON por evento en ~/.fruquis/voice.log
    (al pasar de ~1 MB se guarda como voice.log.1 y se empieza otro)."""
    try:
        with _log_lock:
            if LOG.exists() and LOG.stat().st_size > 1_000_000:
                LOG.replace(LOG.with_name("voice.log.1"))
            LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "evento": evento, **datos}, ensure_ascii=False) + "\n")
    except OSError:
        pass  # el registro nunca debe tumbar al asistente


@contextmanager
def _ipv4():
    """Durante la descarga solo IPv4: en algunas redes la ruta IPv6 a Hugging Face reinicia la conexión (WinError 10054) y la IPv4 funciona."""
    orig = socket.getaddrinfo
    socket.getaddrinfo = lambda *a, **k: [r for r in orig(*a, **k) if r[0] == socket.AF_INET] or orig(*a, **k)
    try:
        yield
    finally:
        socket.getaddrinfo = orig


def _norm(t: str) -> list[str]:
    t = unicodedata.normalize("NFD", t.lower())
    return re.findall(r"[a-z0-9ñ]+", "".join(c for c in t if unicodedata.category(c) != "Mn"))


def collapse_loops(text: str) -> tuple[str, list]:
    """Quita los bucles que Whisper inventa con audio corto o dudoso («Mutama Mutama Mutama…», «Ayax Melyum, Ayax Melyum…»): una pauta de 1 a 4
    palabras repetida 3 veces seguidas o más queda en una sola. Devuelve (texto, pautas que se repetían)."""
    toks, cycles = text.split(), []
    while True:
        keys = ["".join(_norm(t)) for t in toks]
        for k in range(1, 5):
            for i in range(len(toks) - 3 * k + 1):
                if keys[i:i + k] == keys[i + k:i + 2 * k] == keys[i + 2 * k:i + 3 * k]:
                    j = i + k
                    while keys[j:j + k] == keys[i:i + k] and j + k <= len(toks):
                        j += k
                    cycles.append(" ".join(toks[i:i + k]))
                    toks = toks[:i + k] + toks[j:]
                    break
            else:
                continue
            break
        else:
            return " ".join(toks), cycles


def split_wake(text: str, name, *more) -> tuple[bool, str]:
    """(¿dijo el nombre?, lo que dijo después). `name`: el nombre o una lista de nombres y apodos. Tolera errores del reconocedor con nombres raros
    (similitud fonética ≥ 0.75, ≥ 0.7 en nombres de 5 letras o más)."""
    words = _norm(text)
    for nm in ([name] if isinstance(name, str) else list(name)) + list(more):
        target = _phon("".join(_norm(nm)))
        if not words or not target:
            continue
        thr = 0.7 if len(target) >= 5 else 0.75
        for n in (1, 2, 3):  # el reconocedor parte los nombres raros: «Ayax» → «hay ax»
            for i in range(len(words) - n + 1):
                if SequenceMatcher(None, _phon("".join(words[i:i + n])), target).ratio() >= thr:
                    return True, " ".join(words[i + n:])
    return False, ""


STOP = {"detener", "parar", "detente", "para", "cancela", "cancelar"}


def is_stop(text: str, name, awake: bool = False) -> bool:
    """«<nombre> detener/parar/detente/para/cancela/cancelar» (o la palabra sola si ya dijo el nombre). «detener» y «detente» valen también sin
    nombre; «para» o «cancela» sueltas no, porque salen en cualquier frase."""
    w = _norm(text)
    if w in (["detener"], ["detente"]) or (awake and len(w) == 1 and w[0] in STOP):
        return True
    found, rest = split_wake(text, name)
    return found and _norm(rest) in [[s] for s in STOP]


def _phon(w: str) -> str:
    """Aproximación fonética en español: y/ll, c/k/qu, z/s, v/b, h muda, x = ks."""
    for a, b in (("ll", "y"), ("qu", "k"), ("ce", "se"), ("ci", "si"), ("c", "k"), ("z", "s"), ("v", "b"), ("h", ""), ("x", "ks"), ("w", "gu"), ("y", "i")):
        w = w.replace(a, b)
    return w


VOCAB = ("VS Code", "Visual Studio Code", "Chrome", "Firefox")  # palabras técnicas que Whisper en español suele deformar
# «vscode», «vs code», «visual studio code», «estudio(s) code(s/count)», «bi es code»…: todo es el editor
CODE_RE = re.compile(r"\b(?:v\.?\s?s\.?\s?code|vscode|(?:visual\s+)?estudios?\s+(?:code|codes|count|cod|coud)|visual\s+studio(?:\s+code)?|studio\s+(?:code|count))\b", re.I)

class Voice(QObject):
    woke = Signal()  # dijo el nombre solo: queda escuchando la orden
    heard = Signal(str)  # orden dictada
    stop = Signal()  # dijo solo «detener»
    problem = Signal(str)
    status = Signal(str)  # avisos de progreso (instalación, descarga del modelo)
    progress = Signal(int)  # % de la descarga del modelo (0-100)
    ready = Signal()  # modelo cargado y micrófono abierto
    level = Signal(int)  # volumen del micrófono (0-100), para el medidor de Ajustes
    raw = Signal(str)  # todo lo que entendió, tenga o no el nombre (diagnóstico)
    unsure = Signal(str)  # entendió algo con poca confianza: no se ejecuta, se pide repetirlo
    listening = Signal(bool)  # el botón del micrófono: ya está escuchando (True) / terminó o se canceló (False)

    def __init__(self, name, others=lambda: [], busy=lambda: False):
        super().__init__()
        self.name, self.others, self.busy, self.on, self.gen = name, others, busy, False, 0  # funciones: nombre actual, nombres de todos y si hay una petición en curso
        self.mic = store.get("voice_mic", "")  # nombre del dispositivo de entrada; vacío = el predeterminado
        self.size = store.get("voice_model", "small") if store.get("voice_model", "small") in MODELS else "small"
        self.retries = 0  # reintentos seguidos de abrir el micrófono tras un corte
        self.mic_mode = store.get("button_mode", "chat") == "mic"  # el nombre solo se escucha con el botón flotante en 🎙
        self.wake, self.once, self.live = False, False, False  # wake: escucha su nombre; once: botón del micrófono (una orden sin nombre); live: micrófono abierto

    def set_mic(self, name: str):
        store.put("voice_mic", name)
        self.mic = name
        if self.on:
            self.start()

    @staticmethod
    def inputs(sd) -> list:
        """(índice, dispositivo) de las entradas de una sola API de audio: WASAPI en Windows (los mismos que muestra Ajustes de Windows, con nombre
        completo); en otros sistemas, la predeterminada. Sin filtrar, cada micrófono salía repetido una vez por API (MME, DirectSound, WDM-KS…)."""
        apis = sd.query_hostapis()
        api = next((i for i, a in enumerate(apis) if a["name"] == "Windows WASAPI"), sd.default.hostapi)
        return [(i, d) for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0 and d["hostapi"] == api]

    @classmethod
    def mics(cls) -> list[tuple[str, str]]:
        """(valor guardado, texto) de cada micrófono. En Linux, las entradas reales de PipeWire/Pulse (sin «monitor»), como en Ajustes de sonido."""
        if sys.platform.startswith("linux"):
            try:
                srcs = json.loads(subprocess.run(["pactl", "--format=json", "list", "sources"], capture_output=True, text=True, timeout=5).stdout)
                return [(x["name"], x.get("description") or x["name"]) for x in srcs if not x["name"].endswith(".monitor")]
            except Exception:  # noqa: BLE001 - sin pactl solo queda el predeterminado
                return []
        try:
            import sounddevice as sd
            return [(n, n) for n in dict.fromkeys(d["name"] for _, d in cls.inputs(sd))]
        except Exception:  # noqa: BLE001 - sin sounddevice solo queda el predeterminado
            return []

    def enable(self, on: bool):
        """Escuchar su nombre (Ajustes)."""
        self.wake = on
        self.sync()

    def set_mic_mode(self, on: bool):
        """Botón flotante en modo micrófono (True) o chat (False): en modo chat no escucha el nombre; el clic en modo micrófono sigue dictando sin nombre."""
        self.mic_mode = on
        self.sync()

    def listen_once(self):
        """Botón del micrófono: la próxima frase es una orden, sin decir el nombre. Si no estaba escuchando, abre el micrófono solo para eso."""
        self.once = True
        if self.on and self.live:
            self.listening.emit(True)
        else:
            self.sync()  # el hilo avisa con `listening` cuando el micrófono ya está abierto

    def cancel_once(self):
        if self.once:
            self.once = False
            self.listening.emit(False)
            self.sync()

    def sync(self):
        """Arranca o apaga el micrófono según haga falta (nombre activado o botón armado)."""
        if self.listen_name() or self.once:
            if not self.on:
                self.start()
        else:
            self.on, self.gen, self.live = False, self.gen + 1, False

    def listen_name(self) -> bool:
        return self.wake and self.mic_mode

    def start(self):
        self.on, self.gen = True, self.gen + 1  # cada arranque invalida el hilo anterior: nunca hay dos escuchando (el orden salía duplicado)
        threading.Thread(target=self.loop, args=(self.gen,), daemon=True).start()

    def dir(self):
        return store.HOME / f"whisper-{self.size}"

    def model(self):
        d = self.dir()
        if not self.have():
            d.mkdir(parents=True, exist_ok=True)
            sizes = {**MODEL_FILES, ("model.bin",): MODELS[self.size]}
            total, done, last = sum(sizes.values()), 0, -1
            self.status.emit(f"Descargando el modelo de voz ({MODELS[self.size] // 1_000_000} MB)…")
            with _ipv4():
                for names in sizes:
                    for f in names:  # el vocabulario se llama .txt o .json según el modelo
                        tmp = d / (f + ".part")
                        try:
                            with urllib.request.urlopen(MODEL_URL.format(self.size) + f, timeout=60) as r, open(tmp, "wb") as out:
                                while chunk := r.read(1 << 20):
                                    out.write(chunk)
                                    done += len(chunk)
                                    if (p := min(99, done * 100 // total)) != last:
                                        last = p
                                        self.progress.emit(p)
                        except urllib.error.HTTPError as e:
                            if e.code == 404 and f != names[-1]:
                                continue
                            raise
                        tmp.replace(d / f)
                        break
            self.progress.emit(100)
            self.status.emit("Modelo de voz descargado ✓")
        return d

    def have(self, size: str | None = None) -> bool:
        d = store.HOME / f"whisper-{size or self.size}"
        return all(any((d / f).exists() for f in names) for names in MODEL_FILES) and (d / "model.bin").exists()

    def set_size(self, size: str):
        """Calidad de la voz: «base» (rápida) o «small» (más precisa). Si está escuchando, recarga con el modelo nuevo."""
        store.put("voice_model", size)
        self.size = size
        if self.on:
            self.start()

    def deps(self):
        """Instala faster-whisper y sounddevice con pip la primera vez que faltan (no se puede en la versión empaquetada)."""
        deps.ensure({"faster_whisper": "faster-whisper", "sounddevice": "sounddevice"},
                    lambda pk: self.status.emit("Instalando el reconocimiento de voz (" + ", ".join(pk) + ")…"))

    def loop(self, gen: int):
        """Hilo del micrófono: gana volumen, detecta frases por energía y las pasa a `work` (Whisper tarda más que el audio en llegar)."""
        try:
            self.deps()
            import numpy as np
            import sounddevice as sd
            from faster_whisper import WhisperModel
            whisper = WhisperModel(str(self.model()), device="cpu", compute_type="int8")
            q = Queue()
            threading.Thread(target=self.work, args=(gen, whisper, q), daemon=True).start()
            self.ready.emit()
            log("inicio", personaje=self.name(), micro=self.mic or "predeterminado", modelo=self.size, nombre=self.wake, boton=self.once)
            if self.listen_name():
                self.status.emit(f"¡Listo! Ya te escucho: di «{self.name()}»")
            ref, noise, buf, pre, talk, quiet = 0.0, 0.0, [], [], 0, 0
            dev = self.mic  # si se cambia el micrófono en Ajustes, este hilo termina y arranca otro
            idx = next((i for i, d in self.inputs(sd) if d["name"] == dev), None) if dev else None
            if sys.platform.startswith("linux"):  # la entrada elegida se pasa al servidor de sonido por la API «pulse» de PortAudio
                os.environ.pop("PULSE_SOURCE", None)
                if dev:
                    os.environ["PULSE_SOURCE"] = dev
                    idx = next((i for i, d in enumerate(sd.query_devices()) if d["name"] == "pulse" and d["max_input_channels"] > 0), None)
            wasapi = idx is not None and sd.query_hostapis(sd.query_devices(idx)["hostapi"])["name"] == "Windows WASAPI"
            with sd.RawInputStream(samplerate=RATE, blocksize=BLOCK, dtype="int16", channels=1, device=idx,
                                   extra_settings=sd.WasapiSettings(auto_convert=True) if wasapi else None) as st:  # WASAPI no remuestrea solo
                self.live, self.retries = True, 0
                if self.once:
                    self.listening.emit(True)
                while self.on and self.gen == gen:
                    data, _ = st.read(BLOCK)
                    a = np.frombuffer(bytes(data), np.int16).astype(np.float32)
                    ref = max(float(abs(a).max()), ref * 0.98)  # nivel reciente de la voz
                    a = np.clip(a * min(10.0, max(1.0, 9000 / max(ref, 300))), -32768, 32767)  # micrófonos bajos (portátiles): sube hasta 10×
                    peak = float(abs(a).max())
                    self.level.emit(min(100, int(peak) * 100 // 12000))
                    loud = peak > max(noise * 2.5, 1500)
                    if not loud:
                        noise = 0.95 * noise + 0.05 * peak  # ruido de fondo, para que el umbral se adapte a cada micrófono
                    if loud:
                        talk, quiet = talk + 1, 0
                        buf = buf or list(pre)  # el comienzo de la palabra llega antes de superar el umbral
                        buf.append(a)
                    elif buf:
                        buf.append(a)
                        quiet += 1
                    else:
                        pre = (pre + [a])[-3:]
                    if buf and (quiet * 100 >= END_MS or len(buf) >= MAX_S * 10):  # frase terminada
                        if talk * 100 >= MIN_MS:
                            q.put(np.concatenate(buf) / 32768)
                        buf, talk, quiet = [], 0, 0
        except Exception as e:  # noqa: BLE001 - sin librería, micrófono o red para el modelo: se avisa y se apaga
            if self.gen != gen:  # un hilo ya reemplazado no apaga al nuevo
                return
            if type(e).__name__ == "PortAudioError" and self.retries < 5 and (self.listen_name() or self.once):  # el micrófono se cortó (auriculares que se duermen, otro programa…)
                self.retries += 1
                log("error", donde="micrófono cortado, reintento", detalle=str(e), intento=self.retries)
                time.sleep(2)
                if self.gen == gen:
                    self.start()
                return
            self.on, self.live = False, False
            if self.once:
                self.once = False
                self.listening.emit(False)
            log("error", donde="micro/modelo", detalle=str(e))
            self.problem.emit(f"No pude escuchar ({e}). Prueba a instalar a mano: pip install faster-whisper sounddevice")

    def work(self, gen: int, whisper, q: Queue):
        """Hilo de transcripción: convierte cada frase en texto y decide si es el nombre, una orden o «detener»."""
        awake = 0.0
        while self.on and self.gen == gen:
            try:
                audio = q.get(timeout=0.5)
            except Empty:
                continue
            try:
                name = self.name()
                segs, _ = whisper.transcribe(audio, language="es", beam_size=1, vad_filter=True, condition_on_previous_text=False,
                                             initial_prompt=", ".join([*machine.vocab(), *VOCAB, *self.others(), name]) + ".",  # los nombres de los personajes, para que los escriba bien
                                             no_repeat_ngram_size=3, compression_ratio_threshold=2.0)  # y sin bucles: con audio corto repetía «Mutama Mutama…»
                segs = list(segs)
                text, cycles = collapse_loops(" ".join(s.text.strip() for s in segs).strip())
                text = CODE_RE.sub("VS Code", text)
            except Exception as e:  # noqa: BLE001
                log("error", donde="transcribir", detalle=str(e))
                self.problem.emit(f"No pude transcribir ({e})")
                continue
            now, busy, dec, cmd = time.monotonic(), self.busy(), "ignorado", ""
            looped = bool(cycles)
            lp = min((s.avg_logprob for s in segs), default=0)
            sure = lp >= LOW_CONF
            stutter = looped and all(split_wake(c, name)[0] for c in cycles)  # solo repitió el nombre: «Mutama Mutama abre…» sí vale
            if _norm(text) and looped and not stutter and not (split_wake(text, name)[0] and not split_wake(text, name)[1]):
                dec = "bucle"  # Whisper se repitió con otras palabras: el texto no es de fiar y no se ejecuta (solo vale si quedó el nombre solo)
            elif _norm(text):
                self.raw.emit(text)
                if is_stop(text, name, now < awake or busy):  # con una petición en curso basta «cancela» o «para»
                    awake, dec = 0.0, "alto"
                    self.stop.emit()
                elif speech.speaking():  # es su propia respuesta en voz alta (solo «detener» la interrumpe)
                    dec = "propia_voz"
                elif self.once:  # botón del micrófono: la frase es la orden, sin nombre
                    if sure:
                        awake, dec, cmd, self.once = 0.0, "orden_boton", text, False
                        self.heard.emit(text)
                        self.listening.emit(False)
                        self.sync()
                    else:  # poca confianza: sigue armado para que lo repitas
                        dec = "dudosa"
                        self.unsure.emit(text)
                elif now < awake:
                    found, rest = split_wake(text, name)
                    if sure:
                        awake, dec, cmd = 0.0, "orden", rest if found and rest else text  # si repite el nombre, se lo quita
                        self.heard.emit(cmd)
                    else:
                        awake, dec = now + AWAKE_S, "dudosa"
                        self.unsure.emit(text)
                else:
                    found, rest = split_wake(text, name)
                    if found and rest and not sure:
                        awake, dec = now + AWAKE_S, "dudosa"  # entendió el nombre pero no la orden: espera que la repitas sin el nombre
                        self.unsure.emit(text)
                    elif found and rest:
                        dec, cmd = "orden", rest
                        self.heard.emit(rest)
                    elif found:
                        awake, dec = now + AWAKE_S, "despertar"
                        self.woke.emit()
            else:
                dec = "vacio"  # Whisper no entendió nada (ruido, tos…)
            log("oido", texto=text, decision=dec, orden=cmd, personaje=name, duracion=round(len(audio) / RATE, 1), esperando_orden=now < awake or dec == "despertar",
                ocupado=busy, bucle=looped, logprob=round(lp, 2), sin_voz=round(max((s.no_speech_prob for s in segs), default=0), 2))


if __name__ == "__main__":
    assert split_wake("hola Fruquis abre el navegador", "Fruquis") == (True, "abre el navegador")
    assert split_wake("fruqui", "Fruquis")[0] and split_wake("Fruquis", "Fruquis") == (True, "")
    assert split_wake("qué hora es", "Fruquis") == (False, "")
    assert split_wake("hay ax abre el navegador", "Ayax") == (True, "abre el navegador")
    assert split_wake("a ya ax", "Ayax")[0] and not split_wake("hola buenas tardes", "Ayax")[0]
    print("ok")
