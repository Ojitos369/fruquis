package com.ojitos369.fruquis

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Context
import android.content.Intent
import android.graphics.Path
import android.graphics.Rect
import android.net.Uri
import android.os.Bundle
import android.provider.AlarmClock
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONObject

/** Controlar el teléfono como asistente (estilo Gemini/Bixby): servicio de accesibilidad que lee la pantalla (árbol de accesibilidad, no capturas)
 *  y actúa (tocar, escribir, deslizar, atrás/inicio, abrir apps, enlaces, llamar, alarmas). La IA decide un paso a la vez en JSON (Ai.chat, cualquier
 *  formato). Equivale a control.py del escritorio; se activa en Ajustes de accesibilidad y con «Controlar el teléfono» (prefs "app" → control). */
class PhoneService : AccessibilityService() {
    override fun onServiceConnected() { instance = this }
    override fun onAccessibilityEvent(e: AccessibilityEvent?) {}
    override fun onInterrupt() {}
    override fun onDestroy() { instance = null; super.onDestroy() }

    private var nodes = listOf<AccessibilityNodeInfo>()

    /** Pantalla actual como líneas numeradas «[n] Clase "texto" (clic, editable…) @x,y»; los números sirven para el siguiente paso. */
    private fun screen(): String {
        val root = rootInActiveWindow ?: run { Thread.sleep(500); rootInActiveWindow } ?: return "(no se pudo leer la pantalla)"
        val found = mutableListOf<AccessibilityNodeInfo>()
        val lines = StringBuilder("App al frente: ${root.packageName}\n")
        fun walk(n: AccessibilityNodeInfo) {
            if (found.size >= 150 || lines.length > 6000 || !n.isVisibleToUser) return
            val text = (n.text ?: n.contentDescription ?: n.hintText ?: "").toString().replace("\n", " ").take(80)
            val flags = listOfNotNull("clic".takeIf { n.isClickable || n.isLongClickable }, "editable".takeIf { n.isEditable },
                "desliza".takeIf { n.isScrollable }, "marcado".takeIf { n.isChecked }, "contraseña".takeIf { n.isPassword })
            if (text.isNotEmpty() || flags.isNotEmpty()) {
                val r = Rect().also { n.getBoundsInScreen(it) }
                lines.append("[${found.size}] ${n.className?.toString()?.substringAfterLast('.')} \"$text\" ${flags.joinToString(",")} @${r.centerX()},${r.centerY()}\n")
                found += n
            }
            for (i in 0 until n.childCount) n.getChild(i)?.let(::walk)
        }
        walk(root)
        nodes = found
        return lines.toString()
    }

    private fun tapAt(x: Float, y: Float, ms: Long = 50) {
        dispatchGesture(GestureDescription.Builder().addStroke(GestureDescription.StrokeDescription(Path().apply { moveTo(x, y) }, 0, ms)).build(), null, null)
    }

    private fun swipe(dir: String) {
        val m = resources.displayMetrics
        val (w, h) = m.widthPixels / 2f to m.heightPixels / 2f
        val (dx, dy) = when (dir) { "up" -> 0f to h * 0.6f; "left" -> w * 0.6f to 0f; "right" -> -w * 0.6f to 0f; else -> 0f to -h * 0.6f }  // «down» = ver lo de abajo
        val p = Path().apply { moveTo(w - dx / 2, h - dy / 2); lineTo(w + dx / 2, h + dy / 2) }
        dispatchGesture(GestureDescription.Builder().addStroke(GestureDescription.StrokeDescription(p, 0, 300)).build(), null, null)
    }

    private fun node(a: JSONObject) = nodes.getOrNull(a.optInt("n", -1)) ?: throw Exception("no hay elemento [${a.opt("n")}] en la pantalla")

    private fun start(i: Intent) = startActivity(i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))

    /** Ejecuta un paso y devuelve qué pasó (para el historial que ve la IA). */
    private fun act(a: JSONObject): String {
        when (val k = a.optString("action")) {
            "tap", "long" -> {
                val n = node(a)
                var c: AccessibilityNodeInfo? = n
                while (c != null && !(if (k == "tap") c.isClickable else c.isLongClickable)) c = c.parent  // el texto suele estar dentro del botón
                if (c?.performAction(if (k == "tap") AccessibilityNodeInfo.ACTION_CLICK else AccessibilityNodeInfo.ACTION_LONG_CLICK) != true)
                    Rect().also { n.getBoundsInScreen(it) }.let { tapAt(it.exactCenterX(), it.exactCenterY(), if (k == "tap") 50 else 800) }
            }
            "type" -> {
                val n = node(a)
                if (n.isPassword) return "no escribo contraseñas: que las escriba el usuario"
                val ok = n.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT,
                    Bundle().apply { putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, a.optString("text")) })
                if (!ok) return "no se pudo escribir en [${a.opt("n")}]"
            }
            "enter" -> if (android.os.Build.VERSION.SDK_INT < 30 || !node(a).performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.id))
                return "no se pudo pulsar Intro: toca el botón de buscar/enviar"
            "scroll" -> {
                val fwd = a.optString("dir", "down") in setOf("down", "right")
                if (!(a.has("n") && node(a).performAction(if (fwd) AccessibilityNodeInfo.ACTION_SCROLL_FORWARD else AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD)))
                    swipe(a.optString("dir", "down"))
            }
            "back" -> performGlobalAction(GLOBAL_ACTION_BACK)
            "home" -> performGlobalAction(GLOBAL_ACTION_HOME)
            "recents" -> performGlobalAction(GLOBAL_ACTION_RECENTS)
            "notifications" -> performGlobalAction(GLOBAL_ACTION_NOTIFICATIONS)
            "open_app" -> {
                val want = VoiceService.phon(VoiceService.norm(a.optString("name")).joinToString(""))
                val apps = packageManager.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0)
                    .map { it.activityInfo.packageName to it.loadLabel(packageManager).toString() }
                val (pkg, label) = apps.maxByOrNull { VoiceService.sim(want, VoiceService.phon(VoiceService.norm(it.second).joinToString(""))) }
                    ?.takeIf { VoiceService.sim(want, VoiceService.phon(VoiceService.norm(it.second).joinToString(""))) >= 0.6 }
                    ?: return "no encontré la app «${a.optString("name")}»"
                start(packageManager.getLaunchIntentForPackage(pkg) ?: return "no se puede abrir $label")
                return "abrí $label"
            }
            "open_url" -> start(Intent(Intent.ACTION_VIEW, Uri.parse(a.optString("url"))))
            "dial" -> start(Intent(Intent.ACTION_DIAL, Uri.parse("tel:" + Uri.encode(a.optString("number")))))  // marca; el usuario pulsa llamar
            "alarm" -> start(Intent(AlarmClock.ACTION_SET_ALARM).putExtra(AlarmClock.EXTRA_HOUR, a.optInt("hour"))
                .putExtra(AlarmClock.EXTRA_MINUTES, a.optInt("minute")).putExtra(AlarmClock.EXTRA_MESSAGE, a.optString("label", "Fruquis")))
            "wait" -> {}
            else -> return "acción desconocida «$k»"
        }
        return "ok"
    }

    companion object {
        @Volatile var instance: PhoneService? = null
        private const val STEPS = 20
        /** Globo de pensamiento mientras maneja el teléfono, por acción. */
        val STEP_TEXT = mapOf("tap" to "👆 Tocando…", "long" to "👆 Manteniendo pulsado…", "type" to "⌨️ Escribiendo…", "enter" to "⌨️ Enviando…",
            "scroll" to "📜 Deslizando…", "back" to "↩️ Atrás…", "home" to "🏠 Inicio…", "recents" to "🗂 Apps recientes…", "notifications" to "🔔 Notificaciones…",
            "open_app" to "📱 Abriendo la app…", "open_url" to "🌐 Abriendo…", "dial" to "📞 Marcando…", "alarm" to "⏰ Poniendo la alarma…", "wait" to "⏳ Esperando…")

        /** ¿Está activado el servicio y la casilla «Controlar el teléfono»? */
        fun on(c: Context) = instance != null && c.getSharedPreferences("app", Context.MODE_PRIVATE).getBoolean("control", false)

        private val SYSTEM = " Puedes manejar el teléfono del usuario. En cada turno ves la pantalla actual (elementos numerados) y lo que ya hiciste; " +
            "responde SOLO con un objeto JSON con el siguiente paso:\n" +
            "{\"action\":\"tap\",\"n\":3} tocar · {\"action\":\"long\",\"n\":3} mantener pulsado · {\"action\":\"type\",\"n\":5,\"text\":\"hola\"} escribir (reemplaza el texto) · " +
            "{\"action\":\"enter\",\"n\":5} Intro/buscar en ese campo · {\"action\":\"scroll\",\"dir\":\"down|up|left|right\",\"n\":7} deslizar (n opcional) · " +
            "{\"action\":\"back\"} · {\"action\":\"home\"} · {\"action\":\"recents\"} · {\"action\":\"notifications\"} · " +
            "{\"action\":\"open_app\",\"name\":\"WhatsApp\"} · {\"action\":\"open_url\",\"url\":\"https://… o geo:0,0?q=… o mailto:…\"} · " +
            "{\"action\":\"dial\",\"number\":\"5512345678\"} · {\"action\":\"alarm\",\"hour\":7,\"minute\":30,\"label\":\"…\"} · {\"action\":\"wait\"} · " +
            "{\"action\":\"done\",\"say\":\"respuesta corta para el usuario\"} cuando termines, si no hace falta tocar nada (una pregunta normal) o si no puedes.\n" +
            "Prefiere open_app/open_url/dial/alarm a navegar a mano. Comprueba en la pantalla siguiente que el paso funcionó. No escribas contraseñas, " +
            "no pagues ni borres nada salvo que el usuario lo pida explícitamente; en esos casos detente con done y pídele que lo confirme o lo haga él."

        /** Cumple `goal` paso a paso y devuelve lo que hay que decirle al usuario. Bloqueante (fuera del hilo principal); `cancelled` se revisa entre pasos. */
        fun run(c: Context, goal: String, persona: String, cancelled: () -> Boolean = { false }, onStep: (String) -> Unit = {}): String {
            val s = instance ?: return "Activa «Fruquis» en Ajustes › Accesibilidad para poder manejar el teléfono."
            val ai = Ai(c.getSharedPreferences("ai", Context.MODE_PRIVATE))
            val done = mutableListOf<String>()
            repeat(STEPS) {
                if (cancelled()) return "Detenido ✋"
                val screen = s.screen()
                val prompt = "Pedido del usuario: $goal\n\nPasos hechos:\n${done.takeLast(12).joinToString("\n").ifEmpty { "(ninguno)" }}\n\nPantalla:\n$screen"
                val raw = ai.chat(prompt, persona + SYSTEM)
                VoiceLog.add(c, "paso", "pedido" to goal, "n" to done.size, "ia" to raw.take(500), "pantalla" to screen.take(2500))
                val a = runCatching { JSONObject(Regex("\\{.*\\}", RegexOption.DOT_MATCHES_ALL).find(raw)!!.value) }.getOrNull()
                    ?: return raw  // respondió en texto normal: se toma como respuesta
                if (a.optString("action") == "done") return a.optString("say").ifEmpty { "Listo" }
                if (cancelled()) return "Detenido ✋"
                onStep(a.optString("action"))
                val r = try { s.act(a) } catch (e: Exception) { "error: ${e.message}" }
                done += "${a} → $r"
                VoiceLog.add(c, "resultado", "pedido" to goal, "accion" to a.toString(), "resultado" to r)
                Thread.sleep(if (a.optString("action") == "wait") 2000 else 900)  // deja que la interfaz cambie
            }
            return "Me quedé a medias tras $STEPS pasos 😅"
        }
    }
}
