package com.ojitos369.fruquis

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.AudioManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.widget.Toast
import org.json.JSONObject
import java.io.File
import java.text.Normalizer
import java.util.Locale
import kotlin.math.roundToInt

/** Asistente por voz: escucha en segundo plano (servicio en primer plano con micrófono) y, al oír el nombre del personaje, toma lo que sigue
 *  como pedido: «Fruquis, ¿qué hora es?» o «Fruquis» (te escucho…) y luego la orden. Responde por la API de chat (Ai.kt) y en voz alta.
 *  Paridad con fruquis/voice.py (mismo criterio de nombre y 8 s para dictar tras decir solo el nombre). */
class VoiceService : Service() {
    private val h = Handler(Looper.getMainLooper())
    private var rec: SpeechRecognizer? = null
    private var tts: TextToSpeech? = null
    private var awake = 0L
    private var name = "Fruquis"
    private var on = false
    private var job = 0

    override fun onBind(i: Intent?): IBinder? = null

    override fun onStartCommand(i: Intent?, flags: Int, id: Int): Int {
        if (i?.action == STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        val stop = PendingIntent.getService(this, 1, Intent(this, VoiceService::class.java).setAction(STOP), PendingIntent.FLAG_IMMUTABLE)
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CHANNEL, "Asistente por voz", NotificationManager.IMPORTANCE_LOW))
        val n = Notification.Builder(this, CHANNEL).setSmallIcon(android.R.drawable.ic_btn_speak_now).setContentTitle("Fruquis te escucha")
            .setContentText("Di su nombre para hablarle").addAction(android.R.drawable.ic_menu_close_clear_cancel, "Detener", stop).build()
        if (Build.VERSION.SDK_INT >= 30) startForeground(2, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE) else startForeground(2, n)
        if (!on) {
            if (!SpeechRecognizer.isRecognitionAvailable(this)) {
                Toast.makeText(this, "Este teléfono no tiene reconocimiento de voz", Toast.LENGTH_LONG).show()
                stopSelf()
                return START_NOT_STICKY
            }
            on = true
            running = true
            name = MainActivity.activeDir(this).let { d ->
                runCatching { JSONObject(File(d, "character.json").readText()).optString("name", "") }.getOrDefault("").ifEmpty { "Fruquis" }
            }
            applyMic()
            tts = TextToSpeech(this) { tts?.language = Locale("es") }
            listen()
        }
        return START_NOT_STICKY
    }

    /** Micrófono elegido en Ajustes (prefs "app" → mic = id del dispositivo); sin elección o desconectado, el predeterminado. */
    private fun applyMic() {
        if (Build.VERSION.SDK_INT < 31) return
        val am = getSystemService(AudioManager::class.java)
        val id = getSharedPreferences("app", MODE_PRIVATE).getInt("mic", -1)
        am.availableCommunicationDevices.firstOrNull { it.id == id }?.let { am.setCommunicationDevice(it) } ?: am.clearCommunicationDevice()
    }

    private fun listen() {
        if (!on) return
        rec?.destroy()
        rec = SpeechRecognizer.createSpeechRecognizer(this).apply {
            setRecognitionListener(object : RecognitionListener {
                override fun onResults(r: Bundle?) {
                    // un nombre raro rara vez sale como primera hipótesis: se usa la primera que lo contenga (o la orden «detener»)
                    r?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.let { l -> l.firstOrNull { isStop(it) || splitWake(it, name).first } ?: l.firstOrNull() }?.let(::heard)
                    h.postDelayed(::listen, 300)
                }
                override fun onError(e: Int) { h.postDelayed(::listen, if (e == SpeechRecognizer.ERROR_RECOGNIZER_BUSY) 2000 else 500) }  // silencio, ruido…: sigue escuchando
                override fun onReadyForSpeech(p: Bundle?) {}
                override fun onBeginningOfSpeech() {}
                override fun onRmsChanged(v: Float) {}
                override fun onBufferReceived(b: ByteArray?) {}
                override fun onEndOfSpeech() {}
                override fun onPartialResults(p: Bundle?) {}
                override fun onEvent(t: Int, p: Bundle?) {}
            })
            startListening(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE, "es-MX").putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 5)
                .also { if (Build.VERSION.SDK_INT >= 33) it.putStringArrayListExtra(RecognizerIntent.EXTRA_BIASING_STRINGS, arrayListOf(name, "$name abre", "$name detente")) })  // el nombre como texto guía
        }
    }

    private fun heard(text: String) {
        if (isStop(text)) {  // cancela la petición y calla la voz
            job++
            awake = 0
            listenUntil = 0
            tts?.stop()
            Toast.makeText(this, "Detenido ✋", Toast.LENGTH_SHORT).show()
            return
        }
        if (System.currentTimeMillis() < awake) {
            awake = 0
            listenUntil = 0
            return ask(text)
        }
        val (found, rest) = splitWake(text, name)
        if (found && rest.isNotEmpty()) ask(rest)
        else if (found) {
            awake = System.currentTimeMillis() + AWAKE_MS
            listenUntil = awake
            Toast.makeText(this, "🎙 Escuchando…", Toast.LENGTH_LONG).show()  // sin voz: el micrófono captaría al propio TTS
        }
    }

    /** «<nombre> detener/parar/detente/para/cancela/cancelar» (o la palabra sola si ya dijo el nombre); «detener» y «detente» valen sin nombre. Como voice.is_stop. */
    private fun isStop(text: String): Boolean {
        val w = norm(text)
        if (w == listOf("detener") || w == listOf("detente") || (System.currentTimeMillis() < awake && w.size == 1 && w[0] in STOP)) return true
        val (found, rest) = splitWake(text, name)
        return found && rest in STOP
    }

    private fun say(t: String) {
        Toast.makeText(this, t, Toast.LENGTH_LONG).show()
        tts?.speak(t, TextToSpeech.QUEUE_FLUSH, null, "fruquis")
    }

    /** «cambia a Mively», «ponte Savely»…: cambia el personaje activo sin pasar por la IA (como chatui.pick_character). */
    private fun switchChar(q: String): Boolean {
        val w = norm(q)
        if (w.isEmpty() || w[0] !in CHANGE || !(w.size <= 5 || "personaje" in w)) return false
        val rest = phon(w.filter { it !in FILLER }.joinToString(""))
        if (rest.isEmpty()) return false
        val (id, nm) = (MainActivity.charsDir(this).listFiles() ?: emptyArray()).filter { File(it, "character.json").exists() }.map { d ->
            d.name to runCatching { JSONObject(File(d, "character.json").readText()).optString("name", d.name) }.getOrDefault(d.name)
        }.maxByOrNull { sim(rest, phon(norm(it.second).joinToString(""))) }?.takeIf { sim(rest, phon(norm(it.second).joinToString(""))) >= 0.7 } ?: return false
        if (id == MainActivity.activeDir(this).name) say("Ya soy $nm")
        else {
            MainActivity.setActive(this, id)
            if (OverlayService.running) startService(Intent(this, OverlayService::class.java).setAction(OverlayService.RELOAD))
            name = nm
            say("¡Ahora soy $nm!")
        }
        return true
    }

    /** «muévete a la derecha», «deja libre la derecha», «ya puedes ir donde quieras»: se lo manda a la mascota flotante (como chatui.parse_move). */
    private fun petCmd(q: String): Boolean {
        val w = norm(q)
        if (w.isEmpty() || w.size > 9 || "y" in w) return false
        val side = w.firstNotNullOfOrNull { SIDES[it] }
        val corner = "esquina" in w
        val act: Intent = when {
            ("donde" in w && "quieras" in w) || ("deja" in w && "evitar" in w) || ("quita" in w && "libre" in w) ->
                Intent(this, OverlayService::class.java).setAction(OverlayService.FREE)
            ("libre" in w && w[0] in setOf("deja", "dejame", "dejar", "manten", "mantene")) || (w[0] in setOf("evita", "despeja", "no") && side != null) ->
                Intent(this, OverlayService::class.java).setAction(OverlayService.FREE).putExtra("side", side ?: "").putExtra("frac", if (corner) 0.18f else 0.35f)
            (w[0] in MOVERS || "monitor" in w || "pantalla" in w) && ("monitor" in w || "pantalla" in w) && side == null -> { say("Solo tengo una pantalla 😅"); return true }
            w[0] in MOVERS && side != null -> Intent(this, OverlayService::class.java).setAction(OverlayService.MOVE).putExtra("side", side)
            else -> return false
        }
        if (act.action == OverlayService.FREE && act.getStringExtra("side") == "center") { say("¿Qué lado dejo libre: la derecha o la izquierda?"); return true }
        if (!OverlayService.running) { say("Activa primero la mascota flotante"); return true }
        startService(act)
        say(when (act.action) {
            OverlayService.MOVE -> "Me muevo ${if (side == "left") "a la izquierda" else if (side == "right") "a la derecha" else "al centro"}"
            else -> if (act.getStringExtra("side").isNullOrEmpty()) "¡Listo, ando por donde quiera otra vez!" else "Dejo libre ese lado"
        })
        return true
    }

    /** «volumen al 20%», «sube el volumen», «volumen al máximo»…: lo cambia directo y dice el valor REAL que quedó (como control.parse_volume). */
    private fun volumeCmd(q: String): Boolean {
        val w = norm(q)
        if ("volumen" !in w || w.size > 9 || "y" in w) return false
        val n = w.firstNotNullOfOrNull { it.toIntOrNull() ?: NUMS[it] }
        val up = w.any { it in setOf("sube", "subir", "aumenta", "aumentar", "mas") }
        val down = w.any { it in setOf("baja", "bajar", "disminuye", "reduce", "menos") }
        val am = getSystemService(AudioManager::class.java)
        val max = am.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
        val cur = am.getStreamVolume(AudioManager.STREAM_MUSIC) * 100 / max
        val target = when {
            "maximo" in w || "tope" in w -> 100
            "minimo" in w -> 0
            "mitad" in w -> 50
            n != null && (!(up || down) || w.any { it in setOf("a", "al", "en", "hasta") }) -> n.coerceIn(0, 100)
            up || down -> (cur + (n ?: 10) * (if (up) 1 else -1)).coerceIn(0, 100)
            else -> return false
        }
        am.setStreamVolume(AudioManager.STREAM_MUSIC, (target * max / 100.0).roundToInt(), 0)
        say("🔊 Volumen al ${am.getStreamVolume(AudioManager.STREAM_MUSIC) * 100 / max}%")
        return true
    }

    private fun ask(q: String) {
        if (isNewChat(q)) return say("🆕 Chat nuevo")  // este servicio no guarda conversación: cada orden ya empieza de cero
        if (volumeCmd(q)) return
        if (petCmd(q)) return
        if (switchChar(q)) return
        val who = name
        val mine = ++job  // «detener» sube job: la respuesta de esta petición se descarta (la llamada HTTP termina sola)
        Thread {
            val reply = try {
                Ai(getSharedPreferences("ai", MODE_PRIVATE)).chat(q, "Eres $who, un asistente por voz. Responde siempre en español, en una o dos frases cortas.")
            } catch (e: Exception) {
                "No pude responder (${e.message})"
            }
            h.post { if (mine == job) say(reply) }
        }.start()
    }

    override fun onDestroy() {
        on = false
        running = false
        listenUntil = 0
        if (Build.VERSION.SDK_INT >= 31) getSystemService(AudioManager::class.java).clearCommunicationDevice()
        h.removeCallbacksAndMessages(null)
        rec?.destroy()
        tts?.shutdown()
        super.onDestroy()
    }

    companion object {
        const val STOP = "com.ojitos369.fruquis.VOICE_STOP"
        const val CHANNEL = "voice"
        private const val AWAKE_MS = 8000L
        private val NUMS = mapOf("cero" to 0, "diez" to 10, "veinte" to 20, "treinta" to 30, "cuarenta" to 40, "cincuenta" to 50, "sesenta" to 60, "setenta" to 70,
            "ochenta" to 80, "noventa" to 90, "cien" to 100, "ciento" to 100)
        private val SIDES = mapOf("derecha" to "right", "izquierda" to "left", "centro" to "center", "medio" to "center")
        private val MOVERS = setOf("muevete", "mueve", "mover", "ve", "vete", "ir", "anda", "andate", "ponte", "pasate", "camina", "corre", "colocate", "ubicate", "quedate")
        private val NEW_CHAT = setOf("nuevo", "nueva", "otro", "otra", "limpia", "limpiar", "borra", "borrar", "reinicia", "reiniciar", "resetea", "empieza", "empezar",
            "comienza", "comenzar", "vacia")

        /** «nuevo chat», «chat nuevo», «limpia el chat»…: cortas, como chatui.is_new_chat. */
        fun isNewChat(t: String): Boolean = norm(t).let { w -> w.size in 1..5 && w.any { it in setOf("chat", "conversacion", "charla") } && w.any { it in NEW_CHAT } }

        private val STOP = setOf("detener", "parar", "detente", "para", "cancela", "cancelar")
        private val CHANGE = setOf("cambia", "cambiar", "cambiate", "cambiame", "pon", "ponme", "ponte", "activa", "usa", "quiero", "habla", "hablar", "dame")
        private val FILLER = CHANGE + setOf("a", "al", "de", "con", "el", "la", "personaje", "personajes", "mejor", "por", "favor", "ahora", "que", "sea", "otro")
        @Volatile var running = false
        /** Hasta cuándo está esperando la orden: la mascota muestra «listening» (o «talking», por FALLBACK en Sprite.kt). */
        @Volatile var listenUntil = 0L

        private fun norm(t: String) = Normalizer.normalize(t.lowercase(), Normalizer.Form.NFD).replace(Regex("\\p{Mn}"), "")
            .let { Regex("[a-z0-9ñ]+").findAll(it).map { m -> m.value }.toList() }

        private fun sim(a: String, b: String): Double {  // 1 - distancia de Levenshtein normalizada
            var prev = IntArray(b.length + 1) { it }
            for (i in 1..a.length) {
                val cur = IntArray(b.length + 1).also { it[0] = i }
                for (j in 1..b.length) cur[j] = minOf(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + if (a[i - 1] == b[j - 1]) 0 else 1)
                prev = cur
            }
            return 1.0 - prev[b.length].toDouble() / maxOf(1, maxOf(a.length, b.length))
        }

        /** (¿dijo el nombre?, lo que dijo después). Tolera errores del reconocedor (similitud ≥ 0.75), como voice.split_wake. */
        fun splitWake(text: String, name: String): Pair<Boolean, String> {
            val w = norm(text)
            val t = phon(norm(name).joinToString(""))
            if (w.isEmpty() || t.isEmpty()) return false to ""
            for (n in 1..3)  // el reconocedor parte los nombres raros: «Ayax» → «hay ax»
                for (i in 0..w.size - n)
                    if (sim(phon(w.subList(i, i + n).joinToString("")), t) >= 0.75) return true to w.drop(i + n).joinToString(" ")
            return false to ""
        }

        /** Aproximación fonética en español, como voice._phon. */
        private fun phon(s: String) = listOf("ll" to "y", "qu" to "k", "ce" to "se", "ci" to "si", "c" to "k", "z" to "s", "v" to "b", "h" to "", "x" to "ks", "w" to "gu")
            .fold(s) { acc, (a, b) -> acc.replace(a, b) }
    }
}
