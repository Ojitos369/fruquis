"""Generación de animaciones en segundo plano y en paralelo: se eligen varias (faltantes o para reemplazar) y se generan a la vez con Codex
sin bloquear la interfaz. El gestor vive fuera de las vistas: puedes cambiar de pantalla o cerrar la ventana mientras trabaja."""
import itertools
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

from . import anatomy, imagegen, sprites, store

QUEUED, RUNNING, READY, FAILED, CANCELLED, APPLIED = "en cola", "generando", "lista", "error", "cancelada", "aplicada"
_ids = itertools.count(1)


@dataclass
class Job:
    cid: str
    anim: str
    replace: bool = False
    id: int = field(default_factory=lambda: next(_ids))
    status: str = QUEUED
    msg: str = ""
    plan: dict | None = None
    error: str = ""


class GenManager(QObject):
    changed = Signal()       # cualquier cambio de estado: las vistas se redibujan
    finished = Signal(object)  # un trabajo terminó (lista o error): la mascota avisa
    all_done = Signal(int, int)  # (listas, con error) cuando ya no queda nada pendiente

    def __init__(self):
        super().__init__()
        self.jobs: list[Job] = []
        self.futures: dict[int, object] = {}
        self.lock = threading.Lock()
        self.pool: ThreadPoolExecutor | None = None
        self.batch: list[Job] = []

    # ---- consulta ----
    def pending(self) -> int:
        return sum(j.status in (QUEUED, RUNNING) for j in self.jobs)

    def busy(self, cid: str, anim: str) -> bool:
        return any(j.cid == cid and j.anim == anim and j.status in (QUEUED, RUNNING) for j in self.jobs)

    # ---- lanzar ----
    def start(self, cid: str, anims: list) -> list:
        """Encola las animaciones (ya en curso se omiten) y las genera en paralelo. Si falta la hoja neutral, se crea UNA vez antes de empezar."""
        c = sprites.get(cid)
        new = [Job(cid, a, a in c.anims) for a in anims if not self.busy(cid, a)]
        if not new:
            return []
        self.jobs.extend(new)
        self.batch = new
        workers = max(1, min(6, int(store.get("parallel", 3))))
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="fruquis-gen")
        threading.Thread(target=self.run_batch, args=(cid, new), daemon=True).start()
        self.changed.emit()
        return new

    def set(self, job: Job, **kw):
        for k, v in kw.items():
            setattr(job, k, v)
        self.changed.emit()

    def run_batch(self, cid: str, jobs: list):
        anatomy.ensure(cid)  # identidad y anatomía: una sola vez, antes de repartir el trabajo
        c = sprites.get(cid)
        if not c.neutral:  # la hoja neutral es la base de todas: una sola vez, antes de repartir el trabajo
            for j in jobs:
                self.set(j, msg="creando la hoja neutral…")
            try:
                imagegen.make_neutral(cid, key=("neutral", cid))
            except SystemExit as e:
                for j in jobs:
                    self.set(j, status=FAILED, error=str(e))
                    self.finished.emit(j)
                return self.check_done()
        for j in jobs:
            if j.status == QUEUED:
                self.futures[j.id] = self.pool.submit(self.work, j)

    def work(self, job: Job):
        if job.status == CANCELLED:
            return
        self.set(job, status=RUNNING, msg="generando con ChatGPT…")
        try:
            c = sprites.get(job.cid)
            text = sprites.prompt(c, job.anim, background=store.get("prompt_bg", "#FF00FF"))
            plan = imagegen.make_animation(job.cid, job.anim, text, lambda m: self.set(job, msg=m), key=job.id)
            if job.status == CANCELLED:
                return
            self.set(job, status=READY, plan=plan, msg="lista para revisar")
        except SystemExit as e:
            self.set(job, status=CANCELLED if "cancelada" in str(e) else FAILED, error=str(e), msg="")
        except Exception as e:  # noqa: BLE001 - se muestra en la lista
            self.set(job, status=FAILED, error=f"{type(e).__name__}: {e}", msg="")
        self.finished.emit(job)
        self.check_done()

    def check_done(self):
        if self.batch and not self.pending():
            ok = sum(j.status == READY for j in self.batch)
            bad = sum(j.status == FAILED for j in self.batch)
            self.batch = []
            self.all_done.emit(ok, bad)

    # ---- acciones sobre trabajos ----
    def cancel(self, job: Job):
        if job.status == QUEUED:
            if f := self.futures.get(job.id):
                f.cancel()
            self.set(job, status=CANCELLED, msg="")
        elif job.status == RUNNING:
            self.set(job, status=CANCELLED, msg="")
            imagegen.cancel(job.id)
        self.check_done()

    def cancel_all(self):
        for j in list(self.jobs):
            self.cancel(j)

    def apply(self, job: Job, pet=None) -> list:
        """Aplica el resultado tal cual lo detectó el importador (conserva fps y modo si la animación ya existía)."""
        c = sprites.get(job.cid)
        old = c.anims.get(job.anim, {})
        mode = "pingpong" if old.get("pingpong") else ("loop" if old.get("loop", True) else "once")
        log = sprites.apply(job.cid, job.plan["rows"], [{"name": job.anim, "fps": old.get("fps", 8), "mode": mode, "rows": list(range(len(job.plan["rows"])))}])
        if pet and job.cid == pet.char.id:
            pet.refresh_character(sprites.get(job.cid))
        self.set(job, status=APPLIED, msg="aplicada")
        return log

    def clear_finished(self):
        self.jobs = [j for j in self.jobs if j.status in (QUEUED, RUNNING, READY)]
        self.changed.emit()
