package com.ojitos369.fruquis

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
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
import android.speech.tts.UtteranceProgressListener
import android.widget.Toast
import org.json.JSONObject
import java.io.File
import java.text.Normalizer
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.roundToInt

/** Asistente por voz. Dos entradas: la orden ya dictada desde el botón del asistente (AssistActivity → ASK) y la escucha activa (LISTEN, mosaico
 *  de ajustes rápidos ListenTile): escucha en segundo plano y, al oír el nombre del personaje, toma lo que sigue como pedido: «Mively, ¿qué hora es?»
 *  o «Mively» (te escucho…) y luego la orden. Responde por la API de chat (Ai.kt) en voz alta y con globos; si «Controlar el teléfono» está activo,
 *  lo maneja (PhoneService). Paridad con fruquis/voice.py (mismo criterio de nombre y 8 s para dictar tras decir solo el nombre). */
class VoiceService : Service() {
    private val h = Handler(Looper.getMainLooper())
    private var rec: SpeechRecognizer? = null
    private var tts: TextToSpeech? = null
    private var awake = 0L
    private var name = "Fruquis"
    private var on = false  // escucha activa
    private var job = 0
    private var pending: String? = null  // lo que hay que decir antes de que el motor de voz esté listo

    override fun onBind(i: Intent?): IBinder? = null

    override fun onStartCommand(i: Intent?, flags: Int, id: Int): Int {
        if (i?.action == STOP) {  // mosaico o «Detener» de la notificación: deja de escuchar y descarta la respuesta en curso
            cancel()
            stopSelf()
            return START_NOT_STICKY
        }
        if (tts == null) name = MainActivity.activeDir(this).let { d ->
            runCatching { JSONObject(File(d, "character.json").readText()).optString("name", "") }.getOrDefault("").ifEmpty { "Fruquis" }
        }
        val listening = on || i?.action == LISTEN
        val stop = PendingIntent.getService(this, 1, Intent(this, VoiceService::class.java).setAction(STOP), PendingIntent.FLAG_IMMUTABLE)
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CHANNEL, "Asistente por voz", NotificationManager.IMPORTANCE_LOW))
        val n = Notification.Builder(this, CHANNEL).setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle(if (listening) "$name te escucha" else "$name te atiende")
            .setContentText(if (listening) "Di «$name» y tu orden" else "Respondiendo a tu orden").setOngoing(true)
            .addAction(android.R.drawable.ic_menu_close_clear_cancel, "Detener", stop).build()
        try {
            if (Build.VERSION.SDK_INT >= 30) startForeground(2, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE) else startForeground(2, n)
        } catch (e: Exception) {  // sin permiso de micrófono o arrancado desde segundo plano
            VoiceLog.add(this, "error", "donde" to "startForeground", "detalle" to e.message)
        }
        if (tts == null) tts = TextToSpeech(this) { st ->
            if (st != TextToSpeech.SUCCESS) { pending = null; if (!on) stopSelf(); return@TextToSpeech }
            tts?.language = Locale("es")
            tts?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {  // orden suelta del botón: al terminar de hablar se cierra
                override fun onDone(u: String?) { h.post { if (!on && job == done) stopSelf() } }
                @Deprecated("") override fun onError(u: String?) = onDone(u)
                override fun onStart(u: String?) {}
            })
            pending?.let { tts?.speak(it, TextToSpeech.QUEUE_FLUSH, null, "fruquis") }
            pending = null
        }
        when (i?.action) {
            ASK -> i.getStringExtra("text")?.let { ask(it, "boton") } ?: if (!on) stopSelf() else Unit
            WAKE -> {  // botón del asistente con la escucha activa (dos reconocedores chocan): lo siguiente que oiga es la orden, sin decir el nombre
                awake = System.currentTimeMillis() + AWAKE_MS
                listenUntil = awake
                note("🎙 Escuchando…", AWAKE_MS, true)
            }
            LISTEN -> if (!on) {
                if (!SpeechRecognizer.isRecognitionAvailable(this)) {
                    note("Este teléfono no tiene reconocimiento de voz")
                    stopSelf()
                    return START_NOT_STICKY
                }
                on = true
                running = true
                applyMic()
                VoiceLog.add(this, "inicio", "personaje" to name)
                ListenTile.refresh(this)
                listen()
            }
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

    /** Lo que oye la escucha activa: solo actúa si dijo el nombre (o justo después de decirlo), como voice.py. */
    private fun heard(text: String) {
        val waiting = System.currentTimeMillis() < awake
        VoiceLog.add(this, "oido", "texto" to text, "esperando_orden" to waiting)
        if (isStop(text)) {  // cancela la petición y calla la voz
            VoiceLog.add(this, "detenido", "texto" to text)
            cancel()
            note("Detenido ✋", 2500)
            return
        }
        if (waiting) {
            awake = 0
            listenUntil = 0
            return ask(text)
        }
        val (found, rest) = splitWake(text, name)
        if (found && rest.isNotEmpty()) ask(rest)
        else if (found) {
            awake = System.currentTimeMillis() + AWAKE_MS
            listenUntil = awake
            note("🎙 Escuchando…", AWAKE_MS, true)  // sin voz: el micrófono captaría al propio TTS
        }
    }

    /** «<nombre> detener/parar/detente/para/cancela/cancelar» (o la palabra sola si ya dijo el nombre); «detener» y «detente» valen sin nombre. Como voice.is_stop. */
    private fun isStop(text: String): Boolean {
        val w = norm(text)
        if (w == listOf("detener") || w == listOf("detente") || (System.currentTimeMillis() < awake && w.size == 1 && w[0] in STOP_WORDS)) return true
        val (found, rest) = splitWake(text, name)
        return found && rest in STOP_WORDS
    }

    private fun cancel() {
        job++
        awake = 0
        listenUntil = 0
        tts?.stop()
    }

    private fun say(t: String) {
        note(t)
        done = job
        if (tts?.speak(t, TextToSpeech.QUEUE_FLUSH, null, "fruquis") != TextToSpeech.SUCCESS) pending = t  // aún iniciando: lo dice al estar listo
    }

    /** Globo junto a la mascota flotante (como en el escritorio); sin mascota, un aviso normal. */
    private fun note(t: String, ms: Long = maxOf(6000L, t.length * 70L), thought: Boolean = false) {
        if (!OverlayService.bubble(this, t, ms, thought)) Toast.makeText(this, t, Toast.LENGTH_LONG).show()
    }

    private var done = -1  // job de la última respuesta dicha (para cerrar el servicio de una orden suelta solo al terminar la última)

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

    private fun ask(q: String, src: String = "voz") {
        VoiceLog.add(this, "pedido", "texto" to q, "origen" to src, "personaje" to name, "telefono" to PhoneService.on(this))
        if (norm(q).let { it.size in 1..2 && it.last() in STOP_WORDS }) {  // «detente», «cancela»: descarta lo que estaba haciendo
            VoiceLog.add(this, "detenido", "texto" to q)
            cancel()
            return say("Detenido ✋")
        }
        if (isNewChat(q)) return say("🆕 Chat nuevo")  // este servicio no guarda conversación: cada orden ya empieza de cero
        if (volumeCmd(q)) return
        if (petCmd(q)) return
        if (switchChar(q)) return
        val who = name
        val mine = ++job  // otra orden o «detener» suben job: la respuesta de esta petición se descarta (la llamada HTTP termina sola)
        OverlayService.bubble(this, "💭 Pensando…", 300_000, true)  // como el globo de pensamiento del escritorio (sin mascota no se avisa)
        Thread {
            val reply = try {
                val persona = "Eres $who, un asistente por voz. Responde siempre en español, en una o dos frases cortas."
                if (PhoneService.on(this)) PhoneService.run(this, q, persona, { mine != job }) { a ->
                    if (mine == job) OverlayService.bubble(this, PhoneService.STEP_TEXT[a] ?: "📱 …", 300_000, true)
                }  // «abre WhatsApp y escríbele a…»
                else Ai(getSharedPreferences("ai", MODE_PRIVATE)).chat(q, persona)
            } catch (e: Exception) {
                "No pude responder (${e.message})"
            }
            VoiceLog.add(this, "respuesta", "pedido" to q, "respuesta" to reply, "descartada" to (mine != job))
            h.post { if (mine == job) say(reply) }
        }.start()
    }

    override fun onDestroy() {
        on = false
        running = false
        listenUntil = 0
        ListenTile.refresh(this)
        if (Build.VERSION.SDK_INT >= 31) getSystemService(AudioManager::class.java).clearCommunicationDevice()
        h.removeCallbacksAndMessages(null)
        rec?.destroy()
        tts?.shutdown()
        super.onDestroy()
    }

    companion object {
        const val STOP = "com.ojitos369.fruquis.VOICE_STOP"
        const val ASK = "com.ojitos369.fruquis.VOICE_ASK"  // extra "text": orden ya dictada (botón del asistente)
        const val LISTEN = "com.ojitos369.fruquis.VOICE_LISTEN"  // escucha activa (mosaico)
        const val WAKE = "com.ojitos369.fruquis.VOICE_WAKE"
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

        private val STOP_WORDS = setOf("detener", "parar", "detente", "para", "cancela", "cancelar")
        private val CHANGE = setOf("cambia", "cambiar", "cambiate", "cambiame", "pon", "ponme", "ponte", "activa", "usa", "quiero", "habla", "hablar", "dame")
        private val FILLER = CHANGE + setOf("a", "al", "de", "con", "el", "la", "personaje", "personajes", "mejor", "por", "favor", "ahora", "que", "sea", "otro")
        @Volatile var running = false  // escucha activa
        /** Hasta cuándo está esperando la orden (AssistActivity o tras decir el nombre): la mascota muestra «listening» (o «talking», por FALLBACK en Sprite.kt). */
        @Volatile var listenUntil = 0L

        fun norm(t: String) = Normalizer.normalize(t.lowercase(), Normalizer.Form.NFD).replace(Regex("\\p{Mn}"), "")
            .let { Regex("[a-z0-9ñ]+").findAll(it).map { m -> m.value }.toList() }

        fun sim(a: String, b: String): Double {  // 1 - distancia de Levenshtein normalizada
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
        fun phon(s: String) = listOf("ll" to "y", "qu" to "k", "ce" to "se", "ci" to "si", "c" to "k", "z" to "s", "v" to "b", "h" to "", "x" to "ks", "w" to "gu")
            .fold(s) { acc, (a, b) -> acc.replace(a, b) }
    }
}

/** Registro como voice.log del escritorio: una línea JSON por evento («oido», «pedido», «respuesta», «paso»…) en files/voice.log
 *  (al pasar de ~1 MB se guarda como voice.log.1). Leerlo: adb shell run-as com.ojitos369.fruquis cat files/voice.log */
object VoiceLog {
    @Synchronized fun add(c: Context, evento: String, vararg datos: Pair<String, Any?>) {
        try {
            val f = File(c.filesDir, "voice.log")
            if (f.length() > 1_000_000) f.renameTo(File(c.filesDir, "voice.log.1"))
            val o = JSONObject().put("t", SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(Date())).put("evento", evento)
            datos.forEach { o.put(it.first, it.second ?: JSONObject.NULL) }
            f.appendText(o.toString() + "\n")
        } catch (_: Exception) {  // el registro nunca debe tumbar al asistente
        }
    }
}
