package com.ojitos369.fruquis

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Rect
import org.json.JSONObject
import java.io.File

/** Personaje y animación actual, compartidos por la pantalla principal y la mascota flotante. Mismo formato que fruquis/sprites.py:
 *  character.json con cell [w,h] y anims {nombre: {sheet,row,frames,fps,loop,pingpong}}; el cuadro i está en (i % cols, row + i / cols). */
class Sprite {
    private var dir = File("")
    private var anims: JSONObject? = null
    private var sheet: Bitmap? = null
    // hojas ya decodificadas: decodificar en cada cambio de animación (al agarrarla, soltarla, aterrizar) trababa el hilo de la
    // interfaz y la mascota flotante se veía cortada o vacía mientras la jalabas
    private val sheets = HashMap<String, Bitmap?>()
    private var cw = 192
    private var ch = 208
    private var row = 0
    private var frames = 1
    private var pingpong = false
    private var loop = true
    private var t0 = 0L
    var fps = 8
        private set
    var current = ""
        private set

    val ok get() = anims != null

    /** Animaciones que trae el personaje (sin la de mirada, que no se reproduce sola). */
    val names: List<String> get() = anims?.keys()?.asSequence()?.filter { it != LOOK }?.sorted()?.toList() ?: emptyList()

    fun load(dir: File): Boolean {
        this.dir = dir
        anims = null
        sheets.clear()
        current = ""
        return try {
            val j = JSONObject(File(dir, "character.json").readText())
            j.optJSONArray("cell")?.let { cw = it.getInt(0); ch = it.getInt(1) }
            anims = j.getJSONObject("anims")
            true
        } catch (e: Exception) {
            false
        }
    }

    /** Cambia de animación (con respaldos) y la reinicia. */
    fun start(name: String) {
        val all = anims ?: return
        try {
            var n = name
            while (!all.has(n) && n in FALLBACK) n = FALLBACK.getValue(n)
            if (!all.has(n)) n = "idle"
            val a = all.getJSONObject(n)
            val sh = File(a.getString("sheet")).name
            sheet = sheets.getOrPut(sh) { BitmapFactory.decodeFile(File(dir, sh).path) }
            row = a.getInt("row")
            frames = maxOf(1, a.getInt("frames"))
            fps = maxOf(1, a.optInt("fps", 8))
            pingpong = a.optBoolean("pingpong")
            loop = a.optBoolean("loop", true)
            current = n
            t0 = System.currentTimeMillis()
        } catch (e: Exception) {
            sheet = null
        }
    }

    /** Dibuja el cuadro que toca en un lienzo de w×h, conservando la proporción, apoyado abajo y centrado. */
    fun draw(c: Canvas, w: Int, h: Int) {
        val s = sheet ?: return
        val i = ((System.currentTimeMillis() - t0) * fps / 1000).toInt()
        val n = if (pingpong && frames > 1) 2 * frames - 2 else frames
        var k = if (loop) i % n else minOf(i, n - 1)
        if (k >= frames) k = n - k
        val cols = maxOf(1, s.width / cw)
        val sx = (k % cols) * cw
        val sy = (row + k / cols) * ch
        if (sx + cw > s.width || sy + ch > s.height) return
        val f = minOf(w / cw.toFloat(), h / ch.toFloat())
        val dw = (cw * f).toInt()
        val dh = (ch * f).toInt()
        val x = (w - dw) / 2
        val y = h - dh
        c.drawBitmap(s, Rect(sx, sy, sx + cw, sy + ch), Rect(x, y, x + dw, y + dh), null)
    }

    companion object {
        const val LOOK = "look"
        // animación de respaldo si el personaje no la trae (igual que sprites.WANTED)
        val FALLBACK = mapOf(
            "eating" to "waving", "cleaning" to "waving", "pampered" to "waving", "talking" to "waving", "listening" to "talking","playing" to "jumping",
            "sleeping" to "waiting", "sitting" to "idle", "dragged" to "waiting", "falling" to "jumping", "climbing" to "running-right", "clinging" to "idle",
            "poking" to "jumping", "reading" to "review", "typing" to "review", "waving" to "idle", "jumping" to "idle", "waiting" to "idle",
        )
        /** Animaciones que se esperan de un personaje y qué hacen (sprites.WANTED, en el mismo orden). */
        val WANTED = linkedMapOf(
            "idle" to "de pie, respirando", "running-right" to "camina/corre a la derecha", "running-left" to "camina/corre a la izquierda",
            "jumping" to "salto de alegría / salto a una ventana", "waving" to "saluda", "failed" to "triste/error", "waiting" to "espera",
            "review" to "pensando/trabajando", "talking" to "habla (mensajes y chat)", "sleeping" to "duerme", "sitting" to "sentada en un borde",
            "dragged" to "colgada mientras la arrastras", "falling" to "cae", "climbing" to "trepa paredes (se dibuja de pie, la app la rota)",
            "clinging" to "agarrada quieta a una pared o al techo (se dibuja de pie, la app la rota)", "poking" to "pica algo",
            "reading" to "lee / mira con atención (cuando analiza tu ventana)", "typing" to "teclea", "pampered" to "la están mimando (feliz, se deja querer)",
            "playing" to "juega", "eating" to "come", "cleaning" to "se limpia",
        )
        /** Nombre en español para la interfaz (sprites.ES); las claves siguen en inglés. */
        private val ES = mapOf("idle" to "reposo", "running-right" to "correr derecha", "running-left" to "correr izquierda", "jumping" to "saltar",
            "waving" to "saludar", "failed" to "fallo", "waiting" to "espera", "review" to "pensar", "talking" to "hablar", "sleeping" to "dormir",
            "sitting" to "sentada", "dragged" to "arrastrada", "falling" to "caer", "climbing" to "trepar", "clinging" to "agarrada", "poking" to "picar",
            "reading" to "leer", "typing" to "teclear", "pampered" to "mimada", "playing" to "jugar", "eating" to "comer", "cleaning" to "limpiar", LOOK to "mirada")

        fun label(name: String) = ES[name] ?: name
    }
}
