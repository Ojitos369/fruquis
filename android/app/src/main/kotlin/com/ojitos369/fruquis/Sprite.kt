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
    private var sheetName = ""
    private var cw = 192
    private var ch = 208
    private var row = 0
    private var frames = 1
    private var pingpong = false
    private var loop = true
    private var t0 = 0L
    var fps = 8
        private set

    val ok get() = anims != null

    fun load(dir: File): Boolean {
        this.dir = dir
        anims = null
        sheetName = ""
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
            val sh = a.getString("sheet")
            if (sh != sheetName) {
                sheet = BitmapFactory.decodeFile(File(dir, File(sh).name).path)
                sheetName = sh
            }
            row = a.getInt("row")
            frames = maxOf(1, a.getInt("frames"))
            fps = maxOf(1, a.optInt("fps", 8))
            pingpong = a.optBoolean("pingpong")
            loop = a.optBoolean("loop", true)
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
        // animación de respaldo si el personaje no la trae (igual que sprites.WANTED)
        val FALLBACK = mapOf(
            "eating" to "waving", "cleaning" to "waving", "pampered" to "waving", "talking" to "waving", "listening" to "talking","playing" to "jumping",
            "sleeping" to "waiting", "sitting" to "idle", "dragged" to "waiting", "falling" to "jumping", "climbing" to "running-right", "clinging" to "idle",
            "waving" to "idle", "jumping" to "idle", "waiting" to "idle",
        )
    }
}
