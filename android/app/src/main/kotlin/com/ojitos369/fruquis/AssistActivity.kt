package com.ojitos369.fruquis

import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.view.Gravity
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import org.json.JSONObject
import java.io.File

/** Botón del asistente (mantener pulsado el lateral/encendido, deslizar desde la esquina…) con Fruquis como «App de asistente digital»:
 *  con la mascota flotando, escucha con globos sobre ella (pone «listening»); si no, con un panel propio abajo. Escucha una orden sin decir el nombre (reconocedor del sistema, sin su cuadro) y se la pasa a VoiceService,
 *  que responde en voz alta y, si está activado, maneja el teléfono. Tocar fuera del panel lo cierra. */
class AssistActivity : Activity() {
    private val h = Handler(Looper.getMainLooper())
    private var rec: SpeechRecognizer? = null
    private lateinit var heard: TextView

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        if (Build.VERSION.SDK_INT >= 27) setShowWhenLocked(true)
        VoiceLog.add(this, "boton", "accion" to intent?.action, "mascota" to OverlayService.running, "escucha_activa" to VoiceService.running)
        if (intent?.action == VoiceService.LISTEN) {  // mosaico «Escucha activa»: arranca la escucha desde aquí (al frente) y se cierra
            if (checkSelfPermission("android.permission.RECORD_AUDIO") == PackageManager.PERMISSION_GRANTED) startListenMode()
            else requestPermissions(arrayOf("android.permission.RECORD_AUDIO"), 2)
            return
        }
        if (VoiceService.running) {  // con la escucha activa (dos reconocedores a la vez chocan): que tome lo siguiente como orden
            startService(Intent(this, VoiceService::class.java).setAction(VoiceService.WAKE))
            return finish()
        }
        val name = runCatching { JSONObject(File(MainActivity.activeDir(this), "character.json").readText()).optString("name", "") }
            .getOrDefault("").ifEmpty { "Fruquis" }
        val dp = resources.displayMetrics.density
        heard = TextView(this).apply { setTextColor(0xFFECECF1.toInt()); textSize = 18f; text = "…" }
        val panel = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding((20 * dp).toInt(), (18 * dp).toInt(), (20 * dp).toInt(), (22 * dp).toInt())
            background = GradientDrawable().apply { setColor(0xFF1C1C24.toInt()); cornerRadius = 24 * dp }
            addView(TextView(context).apply { setTextColor(0xFF8A6AE0.toInt()); textSize = 14f; text = "🎙 $name te escucha" })
            addView(heard)
            setOnClickListener {}  // tocar el panel no lo cierra
            if (OverlayService.running) visibility = android.view.View.GONE  // con la mascota, los globos sustituyen al panel
        }
        setContentView(FrameLayout(this).apply {
            setOnClickListener { finish() }
            addView(panel, FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM).apply { setMargins((12 * dp).toInt(), 0, (12 * dp).toInt(), (24 * dp).toInt()) })
        })
        if (checkSelfPermission("android.permission.RECORD_AUDIO") == PackageManager.PERMISSION_GRANTED) listen()
        else requestPermissions(arrayOf("android.permission.RECORD_AUDIO"), 1)
    }

    override fun onRequestPermissionsResult(req: Int, perms: Array<out String>, res: IntArray) {
        if (res.firstOrNull() != PackageManager.PERMISSION_GRANTED) finish() else if (req == 2) startListenMode() else listen()
    }

    private fun startListenMode() {
        startForegroundService(Intent(this, VoiceService::class.java).setAction(VoiceService.LISTEN))
        finish()
    }

    /** Lo que se oye: en el panel y, si la mascota flota, en su globo. */
    private fun show(t: String, ms: Long = 15000, thought: Boolean = true) {
        heard.text = t
        OverlayService.bubble(this, t, ms, thought)
    }

    private fun listen() {
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            Toast.makeText(this, "Este teléfono no tiene reconocimiento de voz", Toast.LENGTH_LONG).show()
            return finish()
        }
        VoiceService.listenUntil = System.currentTimeMillis() + 15000  // la mascota escucha
        show("🎙 Te escucho…")
        rec = SpeechRecognizer.createSpeechRecognizer(this).apply {
            setRecognitionListener(object : RecognitionListener {
                override fun onPartialResults(p: Bundle?) {
                    p?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.takeIf { it.isNotBlank() }?.let { show("🎙 $it") }
                }
                override fun onResults(r: Bundle?) {
                    val t = r?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()
                    if (t.isNullOrBlank()) return onError(SpeechRecognizer.ERROR_NO_MATCH)
                    VoiceService.listenUntil = 0
                    show(t, 3000, false)
                    startForegroundService(Intent(this@AssistActivity, VoiceService::class.java).setAction(VoiceService.ASK).putExtra("text", t))
                    h.postDelayed(::finish, 400)
                }
                override fun onError(e: Int) {
                    VoiceLog.add(this@AssistActivity, "error", "donde" to "boton", "codigo" to e)
                    VoiceService.listenUntil = 0
                    show("No te oí 🙉", 2500, false)
                    h.postDelayed(::finish, 1200)
                }
                override fun onReadyForSpeech(p: Bundle?) {}
                override fun onBeginningOfSpeech() {}
                override fun onRmsChanged(v: Float) {}
                override fun onBufferReceived(b: ByteArray?) {}
                override fun onEndOfSpeech() {}
                override fun onEvent(t: Int, p: Bundle?) {}
            })
            startListening(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE, "es-MX").putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true))
        }
    }

    override fun onDestroy() {
        h.removeCallbacksAndMessages(null)
        VoiceService.listenUntil = 0
        rec?.destroy()
        super.onDestroy()
    }
}
