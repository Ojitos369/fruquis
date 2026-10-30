package com.ojitos369.fruquis

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Canvas
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import java.io.File
import java.io.InputStream
import java.util.zip.ZipInputStream
import kotlin.concurrent.thread

/** Versión Android de Fruquis: la mascota animada con las mismas hojas de sprites (character.json) y el mismo tamagotchi que el escritorio.
 *  Mantener en paridad con fruquis/care.py (valores de DECAY/FLOOR/ACTIONS) y con el formato de fruquis/sprites.py. */
class MainActivity : Activity() {
    private class Action(val label: String, val anim: String, val fx: IntArray)  // fx: hambre, limpieza, diversión, energía

    private val h = Handler(Looper.getMainLooper())
    private val stats = DoubleArray(4)
    private val prefs by lazy { getSharedPreferences("care", MODE_PRIVATE) }
    private lateinit var pet: PetView
    private lateinit var status: TextView
    private lateinit var floatBtn: Button
    private var current = "idle"
    private var until = 0L

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        loadCare()
        fun button(text: String, onClick: () -> Unit) = Button(this).apply { this.text = text; isAllCaps = false; setOnClickListener { onClick() } }
        fun row(vararg bs: Button) = LinearLayout(this).apply { bs.forEach { addView(it, LinearLayout.LayoutParams(0, -2, 1f)) } }
        pet = PetView()
        status = TextView(this).apply { gravity = Gravity.CENTER }
        floatBtn = button("") { toggleFloat() }
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(24, 48, 24, 24)
            addView(pet, LinearLayout.LayoutParams(-1, 0, 1f))
            addView(status)
            addView(row(*ACTIONS.map { a -> button(a.label) { act(a) } }.toTypedArray()))
            addView(button("Importar personaje (.zip)") {
                startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).setType("*/*").addCategory(Intent.CATEGORY_OPENABLE), 1)
            })
            addView(floatBtn)
            addView(row(button("Hablar") { talkDialog() }, button("Ajustes de IA") { aiDialog() }))
        }
        setContentView(root)
        pet.setOnClickListener { play("waving", 2000) }
        pet.load()
        tick()
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(req: Int, res: Int, data: Intent?) {
        if (req != 1 || res != RESULT_OK || data?.data == null) return
        try {
            contentResolver.openInputStream(data.data!!)!!.use { importZip(it) }
            pet.load()
            toast(if (pet.ok) "Personaje importado" else "El zip no trae character.json")
        } catch (e: Exception) {
            toast("No se pudo importar: ${e.message}")
        }
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_LONG).show()

    // ---- IA por API (Ai.kt / provider.py) ----
    private fun ai() = Ai(getSharedPreferences("ai", MODE_PRIVATE))

    private fun talkDialog() {
        val t = EditText(this)
        AlertDialog.Builder(this).setTitle("Dile algo").setView(t).setNegativeButton("Cancelar", null).setPositiveButton("Enviar") { _, _ ->
            play("talking", 120000)
            val prompt = t.text.toString()
            val ai = ai()
            thread {
                val r = try {
                    ai.chat(prompt, "Eres Fruquis, una mascota tierna. Responde siempre en español, máximo 3 frases.")
                } catch (e: Exception) {
                    "No pude responder (${e.message})"
                }
                runOnUiThread { until = System.currentTimeMillis() + 2000; status.text = r }
            }
        }.show()
    }

    private fun aiDialog() {
        val ai = ai()
        val f = listOf(
            Triple("chat", "kind", "Chat: formato (openai | anthropic)"), Triple("chat", "url", "Chat: URL base (vacío = oficial)"),
            Triple("chat", "key", "Chat: clave"), Triple("chat", "model", "Chat: modelo (vacío = predeterminado)"),
            Triple("image", "url", "Imágenes: URL base (vacío = OpenAI)"), Triple("image", "key", "Imágenes: clave"),
            Triple("image", "model", "Imágenes: modelo (vacío = gpt-image-1)"))
        val fields = f.map { (what, k, hint) ->
            EditText(this).apply {
                this.hint = hint
                setText(ai.p.getString("${what}_$k", ""))
                setSingleLine()
                if (k == "key") inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            }
        }
        val l = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(32, 16, 32, 0); fields.forEach { addView(it) } }
        AlertDialog.Builder(this).setTitle("IA por API").setView(l).setNegativeButton("Cancelar", null).setPositiveButton("Guardar") { _, _ ->
            ai.p.edit().apply { f.forEachIndexed { i, (what, k, _) -> putString("${what}_$k", fields[i].text.toString().trim()) } }.apply()
        }.show()
    }

    // ---- mascota flotante (OverlayService) ----
    private fun toggleFloat() {
        if (OverlayService.running) {
            startService(Intent(this, OverlayService::class.java).setAction(OverlayService.STOP))
            floatBtn.postDelayed(::showFloat, 300)
            return
        }
        if (!pet.ok) return toast("Importa primero un personaje")
        if (!Settings.canDrawOverlays(this)) {  // permiso especial «Mostrar sobre otras apps»: se concede en una pantalla de Ajustes
            toast("Activa «Mostrar sobre otras apps» para Fruquis y vuelve")
            startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
            return
        }
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission("android.permission.POST_NOTIFICATIONS") != PackageManager.PERMISSION_GRANTED)
            requestPermissions(arrayOf("android.permission.POST_NOTIFICATIONS"), 2)  // para ver el aviso con el botón «Quitar»
        startForegroundService(Intent(this, OverlayService::class.java))
        floatBtn.postDelayed(::showFloat, 500)
    }

    private fun showFloat() { floatBtn.text = if (OverlayService.running) "Quitar mascota flotante" else "Mascota flotante" }

    private fun dir() = File(filesDir, "character")

    /** Extrae solo .json/.png/.md y por nombre de archivo (el zip trae <id>/<archivo>): no hay rutas que escapen de la carpeta. */
    private fun importZip(input: InputStream) {
        val tmp = File(filesDir, "character.tmp")
        tmp.deleteRecursively()
        tmp.mkdirs()
        ZipInputStream(input).use { z ->
            var total = 0L
            generateSequence { z.nextEntry }.forEach { e ->
                val n = File(e.name).name
                if (e.isDirectory || !Regex("[\\w.\\- ]+\\.(json|png|md)").matches(n)) return@forEach
                File(tmp, n).outputStream().use { o ->
                    val buf = ByteArray(8192)
                    while (true) {
                        val r = z.read(buf)
                        if (r <= 0) break
                        total += r
                        if (total > 200L shl 20) throw Exception("zip demasiado grande")
                        o.write(buf, 0, r)
                    }
                }
            }
        }
        if (!File(tmp, "character.json").exists()) { tmp.deleteRecursively(); throw Exception("falta character.json") }
        dir().deleteRecursively()
        if (!tmp.renameTo(dir())) throw Exception("no se pudo guardar")
    }

    // ---- tamagotchi (care.py) ----
    private fun loadCare() {
        val at = prefs.getLong("at", System.currentTimeMillis())
        KEYS.forEachIndexed { i, k -> stats[i] = prefs.getFloat(k, 80f).toDouble() }
        advance((System.currentTimeMillis() - at) / 1000.0, true)
    }

    private fun advance(seconds: Double, offline: Boolean) {
        for (i in 0 until 4) {
            val v = stats[i] - DECAY[i] * seconds / 3600
            stats[i] = if (offline) maxOf(minOf(stats[i], FLOOR), v) else maxOf(0.0, v)
        }
        saveCare()
    }

    private fun saveCare() = prefs.edit().apply {
        putLong("at", System.currentTimeMillis())
        KEYS.forEachIndexed { i, k -> putFloat(k, stats[i].toFloat()) }
    }.apply()

    private fun act(a: Action) {
        for (i in 0 until 4) stats[i] = (stats[i] + a.fx[i]).coerceIn(0.0, 100.0)
        saveCare()
        play(a.anim, 3000)
    }

    private fun play(anim: String, ms: Long) {
        current = anim
        until = System.currentTimeMillis() + ms
        pet.start(anim)
        showStatus()
    }

    private fun showStatus() {
        status.text = "🍙 ${stats[0].toInt()}   🫧 ${stats[1].toInt()}   🎾 ${stats[2].toInt()}   ⚡ ${stats[3].toInt()}"
    }

    private fun tick() {
        advance(60.0, false)
        showStatus()
        h.postDelayed(::tick, 60000)
    }

    override fun onResume() { super.onResume(); showFloat(); loadCare(); showStatus(); pet.start(current) }
    override fun onDestroy() { h.removeCallbacksAndMessages(null); super.onDestroy() }

    // ---- sprites (Sprite.kt) ----
    private inner class PetView : View(this@MainActivity) {
        private val sp = Sprite()
        private val step = object : Runnable {
            override fun run() {
                if (until > 0 && System.currentTimeMillis() > until && current != "idle") { current = "idle"; until = 0; sp.start("idle") }
                invalidate()
                postDelayed(this, 1000L / sp.fps)
            }
        }
        val ok get() = sp.ok

        fun load() {
            removeCallbacks(step)
            if (sp.load(dir())) start(current) else invalidate()
        }

        fun start(name: String) {
            removeCallbacks(step)
            if (!sp.ok) return
            sp.start(name)
            post(step)
        }

        override fun onDraw(c: Canvas) = sp.draw(c, width, height)
    }

    companion object {
        // hambre, limpieza, diversión, energía -> puntos por hora (igual que care.DECAY)
        private val KEYS = listOf("hambre", "limpieza", "diversion", "energia")
        private val DECAY = doubleArrayOf(6.0, 4.0, 5.0, 2.0)
        private const val FLOOR = 15.0
        // acción: animación y efectos (igual que care.ACTIONS)
        private val ACTIONS = listOf(
            Action("Comer", "eating", intArrayOf(35, -5, 0, 0)), Action("Limpiar", "cleaning", intArrayOf(0, 50, 0, 0)),
            Action("Jugar", "playing", intArrayOf(-5, 0, 30, -8)), Action("Mimar", "pampered", intArrayOf(0, 0, 25, 3)),
            Action("Dormir", "sleeping", intArrayOf(-3, 0, 0, 40)))
    }
}
