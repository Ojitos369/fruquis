package com.ojitos369.fruquis

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Environment
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.Base64
import android.widget.Toast
import org.json.JSONObject
import java.io.DataInputStream
import java.io.File
import java.io.IOException
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.URL
import java.net.URLDecoder
import java.net.URLEncoder
import java.security.MessageDigest
import java.security.SecureRandom
import java.text.Normalizer
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import kotlin.concurrent.thread

/** Vínculo entre equipos (celular ↔ PC u otro celular): órdenes y archivos de uno al otro. Paridad con fruquis/link.py (mismo protocolo).
 *  Los equipos comparten un código; cada mensaje va firmado con HMAC-SHA256 con él (no se acepta nada sin firma válida, ni repetido, ni viejo).
 *  Dos rutas, primero la local: LAN (aviso UDP por broadcast + HTTP) y relay (servidor aipi: /api/link/send y /api/link/poll). La firma autentica pero NO cifra.
 *  Ajustes en SharedPreferences "link": code, name, relay, accept (ask|auto|off), id. Las llamadas de red son bloqueantes: fuera del hilo principal. */
object Link {
    const val KIND = "phone"
    private const val UDP = 8379
    private const val BEACON_MS = 4000L
    private const val FRESH_MS = 15000L
    private const val SKEW_MS = 300_000L
    private const val CONFIRM_S = 120L
    const val MAX_FILE = 15 * 1024 * 1024
    private const val CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    private val ALIAS = mapOf("pc" to listOf("pc", "computadora", "compu", "laptop", "escritorio", "ordenador"), "phone" to listOf("celular", "telefono", "movil", "cel"))

    class Conf(val code: String, val name: String, val relay: String, val accept: String, val id: String)
    class Peer(var name: String, var kind: String, var ip: String = "", var port: Int = 0, var seen: Long = 0)

    private val peers = ConcurrentHashMap<String, Peer>()
    private val seen = ConcurrentHashMap<String, Long>()
    private val waiting = ConcurrentHashMap<String, Pair<CountDownLatch, BooleanArray>>()  // confirmaciones pendientes: id de la orden → (espera, [aceptada])
    private val busy = AtomicBoolean(false)
    @Volatile private var gen = 0  // cada start() lo incrementa: los hilos de la vuelta anterior terminan solos
    @Volatile private var server: ServerSocket? = null
    @Volatile private var listener: DatagramSocket? = null
    @Volatile private var relayOk: Boolean? = null
    @Volatile private var error = ""

    private fun prefs(c: Context) = c.getSharedPreferences("link", Context.MODE_PRIVATE)

    fun conf(c: Context): Conf {
        val p = prefs(c)
        if (p.getString("id", "").isNullOrEmpty()) p.edit().putString("id", ByteArray(4).also { SecureRandom().nextBytes(it) }.joinToString("") { "%02x".format(it) }).apply()
        return Conf(p.getString("code", "")!!, p.getString("name", "")!!.ifBlank { Build.MODEL }, p.getString("relay", "")!!, p.getString("accept", "ask")!!, p.getString("id", "")!!)
    }

    fun save(c: Context, code: String? = null, name: String? = null, relay: String? = null, accept: String? = null) {
        prefs(c).edit().apply {
            code?.let { putString("code", it) }; name?.let { putString("name", it) }; relay?.let { putString("relay", it) }; accept?.let { putString("accept", it) }
        }.apply()
    }

    fun newCode() = SecureRandom().let { r -> (1..12).map { CHARS[r.nextInt(CHARS.length)] }.joinToString("") }
    fun cleanCode(s: String) = s.uppercase().filter { it in 'A'..'Z' || it in '0'..'9' }
    fun showCode(code: String) = code.chunked(4).joinToString("-")
    private fun room(code: String) = sha256("fruquis-link:$code").take(16)
    private fun sha256(s: String) = MessageDigest.getInstance("SHA-256").digest(s.toByteArray()).joinToString("") { "%02x".format(it) }
    private fun sign(code: String, body: String) =
        Mac.getInstance("HmacSHA256").apply { init(SecretKeySpec(code.toByteArray(), "HmacSHA256")) }.doFinal(body.toByteArray()).joinToString("") { "%02x".format(it) }

    fun norm(s: String) = Normalizer.normalize(s.lowercase(), Normalizer.Form.NFD).replace(Regex("\\p{Mn}+"), "").replace(Regex("\\s+"), " ").trim()

    /** Enlace personal del servidor aipi (con ?key=…) → (base, clave). */
    private fun relayParts(link: String): Pair<String, String> {
        val u = link.trim()
        val key = Regex("[?&]key=([^&]*)").find(u)?.groupValues?.get(1)?.let { URLDecoder.decode(it, "UTF-8") } ?: ""
        return (if (u.startsWith("http")) u.substringBefore("?").substringBefore("/api/").trimEnd('/') else "") to key
    }

    /** Equipos vistos alguna vez en este vínculo: id → (nombre, tipo). */
    private fun known(c: Context): Map<String, Pair<String, String>> {
        val o = runCatching { JSONObject(prefs(c).getString("peers", "{}")!!) }.getOrDefault(JSONObject())
        return o.keys().asSequence().associateWith { o.getJSONObject(it).let { p -> p.optString("n") to p.optString("k") } }
    }

    /** «dile al celular que abra Maps» / «en el otro equipo, abre X» → (nombre del destino o "", orden); null si no habla de otro equipo. */
    fun parse(c: Context, text: String): Pair<String, String>? {
        if (conf(c).code.isEmpty()) return null
        val names = linkedMapOf("otro equipo" to "", "otro dispositivo" to "", "el otro" to "")
        known(c).values.forEach { (n, k) ->
            if (n.isNotEmpty()) names[norm(n)] = n
            ALIAS[k]?.forEach { names.putIfAbsent(it, n) }
        }
        names.remove("")
        val alt = names.keys.sortedByDescending { it.length }.joinToString("|") { Regex.escape(it) }
        val folded = Normalizer.normalize(text.lowercase(), Normalizer.Form.NFD).replace(Regex("\\p{Mn}+"), "")  // misma longitud que el texto en español: los índices valen
        val m = Regex("^\\s*(?:(?:dile|dicele|pidele|mandale)\\s+(?:a|al)\\s+|(?:en|con)\\s+|al\\s+)(?:el\\s+|la\\s+|mi\\s+|tu\\s+)?($alt)\\b[\\s,:;.]*(?:que\\s+)?(.+)",
            RegexOption.DOT_MATCHES_ALL).find(folded) ?: return null
        val order = if (folded.length == text.length) text.substring(m.groups[2]!!.range.first) else m.groupValues[2]
        return (names[norm(m.groupValues[1])] ?: "") to order.trim()
    }

    // ---- ciclo de vida ----
    @Synchronized fun start(c: Context) {
        stop()
        val app = c.applicationContext
        if (conf(app).code.isEmpty()) return
        val g = ++gen
        peers.clear(); error = ""; relayOk = null
        val ss = ServerSocket(0).also { server = it }
        thread(isDaemon = true, name = "link-http") {
            while (g == gen) {
                val s = try { ss.accept() } catch (e: IOException) { break }
                thread(isDaemon = true) { handle(app, s) }
            }
        }
        thread(isDaemon = true, name = "link-beacon") { beacon(app, g, ss.localPort) }
        thread(isDaemon = true, name = "link-listen") { listen(app, g) }
        thread(isDaemon = true, name = "link-poll") { poll(app, g) }
    }

    @Synchronized fun stop() {
        gen++
        runCatching { server?.close() }
        runCatching { listener?.close() }
        server = null; listener = null
    }

    val running get() = server != null

    // ---- recibir ----
    private fun handle(c: Context, s: Socket) = s.use {
        s.soTimeout = 15000
        val inp = DataInputStream(s.getInputStream().buffered())
        fun line(): String { val b = StringBuilder(); while (true) { val x = inp.read(); if (x < 0 || x == '\n'.code) break; if (x != '\r'.code) b.append(x.toChar()) }; return b.toString() }
        var len = 0
        while (true) { val l = line(); if (l.isEmpty()) break; if (l.startsWith("content-length:", true)) len = l.substring(15).trim().toIntOrNull() ?: 0 }
        val ok = len in 1..(MAX_FILE * 2) && try {
            val buf = ByteArray(len).also { inp.readFully(it) }
            receive(c, JSONObject(String(buf)))
        } catch (e: Exception) { false }
        s.getOutputStream().write("HTTP/1.1 ${if (ok) "200 OK" else "403 Forbidden"}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".toByteArray())
    }

    private fun peer(c: Context, id: String, name: String, kind: String, ip: String = "", port: Int = 0) {
        val p = peers.getOrPut(id) { Peer(name, kind) }
        p.name = name; p.kind = kind
        if (ip.isNotEmpty()) { p.ip = ip; p.port = port; p.seen = System.currentTimeMillis() }
        val all = runCatching { JSONObject(prefs(c).getString("peers", "{}")!!) }.getOrDefault(JSONObject())
        if (all.optJSONObject(id)?.let { it.optString("n") == name && it.optString("k") == kind } != true)
            prefs(c).edit().putString("peers", all.put(id, JSONObject().put("n", name).put("k", kind)).toString()).apply()
    }

    /** Verifica un sobre {b, s}: firma, antigüedad, repetidos y destinatario. true = válido (aunque no fuera para este equipo). */
    fun receive(c: Context, env: JSONObject): Boolean {
        val cf = conf(c)
        val body = env.optString("b")
        if (body.isEmpty() || cf.code.isEmpty() || !MessageDigest.isEqual(sign(cf.code, body).toByteArray(), env.optString("s").toByteArray())) return false
        val m = runCatching { JSONObject(body) }.getOrNull() ?: return false
        val id = m.optString("id")
        val now = System.currentTimeMillis()
        if (id.isEmpty() || m.optString("from") == cf.id || Math.abs(now - m.optLong("ts")) > SKEW_MS) return false
        seen.entries.removeIf { now - it.value > 2 * SKEW_MS }
        if (seen.putIfAbsent(id, now) != null) return true  // ya llegó por la otra ruta
        peer(c, m.optString("from"), m.optString("n", "?"), m.optString("k"))
        if (m.optString("to").isNotEmpty() && norm(m.optString("to")) != norm(cf.name)) return true
        if (m.optString("type") == "file") try {
            m.put("path", saveFile(c, m.optString("fname"), Base64.decode(m.optString("data"), Base64.DEFAULT)).absolutePath)
        } catch (e: Exception) {
            m.put("type", "result").put("text", "No pude guardar el archivo (${e.message})")
        }
        m.remove("data")
        thread(isDaemon = true) { onMsg(c, m) }
        return true
    }

    private fun saveFile(c: Context, fname: String, bytes: ByteArray): File {
        val dir = c.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: c.filesDir
        val name = File(fname).name.replace(Regex("[<>:\"/\\\\|?*\\x00-\\x1f]"), "_").trim('.', ' ').ifEmpty { "archivo" }
        var dest = File(dir, name)
        var i = 1
        while (dest.exists()) dest = File(dir, "${name.substringBeforeLast('.')} (${i++}).${name.substringAfterLast('.', "")}".trimEnd('.'))
        dest.writeBytes(bytes)
        return dest
    }

    // ---- LAN ----
    private fun beacon(c: Context, g: Int, port: Int) {
        val s = DatagramSocket().apply { broadcast = true }
        while (g == gen) {
            val cf = conf(c)
            runCatching {
                val d = JSONObject().put("r", room(cf.code)).put("i", cf.id).put("n", cf.name).put("k", KIND).put("p", port).toString().toByteArray()
                s.send(DatagramPacket(d, d.size, InetAddress.getByName("255.255.255.255"), UDP))
            }
            Thread.sleep(BEACON_MS)
        }
        s.close()
    }

    private fun listen(c: Context, g: Int) {
        val s = try { DatagramSocket(null as java.net.SocketAddress?).apply { reuseAddress = true; soTimeout = 1000; bind(InetSocketAddress(UDP)) } } catch (e: Exception) {
            error = "LAN: no pude abrir el puerto $UDP (${e.message})"; return
        }
        listener = s
        val buf = ByteArray(2048)
        while (g == gen) {
            try {
                val p = DatagramPacket(buf, buf.size).also { s.receive(it) }
                val d = JSONObject(String(p.data, 0, p.length)); val cf = conf(c)
                if (d.getString("r") == room(cf.code) && d.getString("i") != cf.id)
                    peer(c, d.getString("i"), d.getString("n"), d.getString("k"), p.address.hostAddress ?: continue, d.getInt("p"))
            } catch (e: java.net.SocketTimeoutException) {
            } catch (e: Exception) {
                if (g != gen) break
            }
        }
        s.close()
    }

    // ---- relay ----
    private fun http(url: String, body: String?, readMs: Int): String {
        val h = URL(url).openConnection() as HttpURLConnection
        h.connectTimeout = 8000; h.readTimeout = readMs
        h.setRequestProperty("User-Agent", "fruquis-android")
        if (body != null) { h.requestMethod = "POST"; h.doOutput = true; h.setRequestProperty("Content-Type", "application/json"); h.outputStream.use { it.write(body.toByteArray()) } }
        val code = h.responseCode
        val text = (if (code < 400) h.inputStream else h.errorStream)?.use { it.readBytes().decodeToString() } ?: ""
        if (code >= 400) throw IOException("HTTP $code")
        return text
    }

    private fun poll(c: Context, g: Int) {
        var after: Long? = null
        while (g == gen) {
            val cf = conf(c)
            val (base, key) = relayParts(cf.relay)
            if (base.isEmpty()) { Thread.sleep(5000); continue }
            try {
                val q = "key=${URLEncoder.encode(key, "UTF-8")}&room=${room(cf.code)}&wait=25" + (after?.let { "&after=$it" } ?: "")
                val d = JSONObject(http("$base/api/link/poll/?$q", null, 40000))
                after = d.getLong("seq"); relayOk = true
                val items = d.getJSONArray("items")
                for (i in 0 until items.length()) receive(c, items.getJSONObject(i).getJSONObject("e"))
            } catch (e: Exception) {
                relayOk = false; error = "Relay: ${e.message}"
                Thread.sleep(5000)
            }
        }
    }

    // ---- enviar ----
    /** Envía a los otros equipos (o a `to`). Devuelve la ruta usada («LAN» o «relay»); lanza Exception si ninguna llegó. */
    fun send(c: Context, type: String, text: String = "", to: String = "", extra: Map<String, String> = emptyMap()): String {
        val cf = conf(c)
        if (cf.code.isEmpty()) throw Exception("Este equipo no está vinculado todavía.")
        val body = JSONObject().put("id", ByteArray(8).also { SecureRandom().nextBytes(it) }.joinToString("") { "%02x".format(it) }).put("from", cf.id).put("n", cf.name)
            .put("k", KIND).put("to", to).put("ts", System.currentTimeMillis()).put("type", type).put("text", text).apply { extra.forEach { (k, v) -> put(k, v) } }.toString()
        val env = JSONObject().put("b", body).put("s", sign(cf.code, body)).toString()
        var sent = false
        for (p in peers.values.toList()) {
            if (p.ip.isNotEmpty() && System.currentTimeMillis() - p.seen < FRESH_MS && (to.isEmpty() || norm(p.name) == norm(to)))
                try { http("http://${p.ip}:${p.port}/", env, 15000); sent = true } catch (e: IOException) {}
        }
        if (sent) return "LAN"
        val (base, key) = relayParts(cf.relay)
        if (base.isEmpty()) throw Exception("El otro equipo no está en tu red y falta el enlace del servidor (relay).")
        try { http("$base/api/link/send/?key=${URLEncoder.encode(key, "UTF-8")}&room=${room(cf.code)}", env, 30000) }
        catch (e: IOException) { throw Exception("No pude llegar al relay (${e.message})") }
        return "relay"
    }

    fun sendFile(c: Context, name: String, bytes: ByteArray, to: String = ""): String {
        if (bytes.size > MAX_FILE) throw Exception("El archivo pesa más de ${MAX_FILE / 1024 / 1024} MB.")
        return send(c, "file", to = to, extra = mapOf("fname" to name, "data" to Base64.encodeToString(bytes, Base64.NO_WRAP)))
    }

    fun status(c: Context): String {
        val cf = conf(c)
        if (cf.code.isEmpty()) return "Sin vincular"
        val lan = peers.values.filter { it.ip.isNotEmpty() && System.currentTimeMillis() - it.seen < FRESH_MS }.map { it.name }
        return "${if (running) "Vinculado" else "Vinculado (servicio detenido)"} · LAN: ${lan.joinToString(", ").ifEmpty { "sin equipos a la vista" }} · relay: " +
            (if (cf.relay.isEmpty()) "sin configurar" else if (relayOk == true) "conectado" else "sin conexión") + (if (error.isNotEmpty()) " · $error" else "")
    }

    // ---- lo que llega ----
    private fun tell(c: Context, text: String) = Handler(Looper.getMainLooper()).post {
        if (!OverlayService.bubble(c, text)) Toast.makeText(c, text, Toast.LENGTH_LONG).show()
    }

    private fun reply(c: Context, to: String, mid: String, text: String) {
        try { send(c, "result", text, to, mapOf("re" to mid)) } catch (e: Exception) { VoiceLog.add(c, "error", "donde" to "vinculo.respuesta", "detalle" to e.message) }
    }

    private fun onMsg(c: Context, m: JSONObject) {
        val who = m.optString("n", "otro equipo")
        VoiceLog.add(c, "vinculo", "tipo" to m.optString("type"), "de" to who, "texto" to m.optString("text").take(300))
        when (m.optString("type")) {
            "result" -> tell(c, "📲 $who: ${m.optString("text")}")
            "file" -> m.optString("path").takeIf { it.isNotEmpty() }?.let { tell(c, "📥 $who te envió «${File(it).name}» (en $it)") }
            "task" -> runTask(c, who, m.optString("id"), m.optString("text"))
        }
    }

    private fun runTask(c: Context, who: String, mid: String, text: String) {
        when (conf(c).accept) {
            "off" -> return reply(c, who, mid, "Ese equipo no acepta órdenes del otro.")
            "ask" -> if (!confirm(c, mid, who, text)) return reply(c, who, mid, "Lo rechazaron en el otro equipo.")
        }
        if (!busy.compareAndSet(false, true)) return reply(c, who, mid, "Ese equipo está ocupado con otra orden; reintenta en un momento.")
        try {
            tell(c, "📲 $who me pide: $text")
            val goal = "(Orden enviada desde otro equipo del usuario, «$who»; ejecútala aquí, en este equipo.)\n$text"
            val persona = Persona.system(c, anims = false)
            val out = if (PhoneService.on(c)) PhoneService.run(c, goal, persona) else Ai(c.getSharedPreferences("ai", Context.MODE_PRIVATE)).chat(goal, persona) +
                "\n(Este teléfono no tiene activado «Controlar el teléfono»: solo pude responder.)"
            reply(c, who, mid, out)
            tell(c, "📲 Listo lo de $who: $out")
        } catch (e: Exception) {
            reply(c, who, mid, "No pude hacerlo (${e.message})")
        } finally {
            busy.set(false)
        }
    }

    /** Pregunta con una notificación (Permitir / Rechazar) y espera la respuesta; sin respuesta a tiempo se rechaza. */
    private fun confirm(c: Context, mid: String, who: String, text: String): Boolean {
        val latch = CountDownLatch(1)
        val ok = BooleanArray(1)
        waiting[mid] = latch to ok
        val nm = c.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(LinkService.ASK, "Órdenes del otro equipo", NotificationManager.IMPORTANCE_HIGH))
        fun pi(allow: Boolean) = PendingIntent.getBroadcast(c, mid.hashCode() * 2 + if (allow) 1 else 0,
            Intent(LinkService.ANSWER).setPackage(c.packageName).putExtra("id", mid).putExtra("ok", allow), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        nm.notify(mid.hashCode(), Notification.Builder(c, LinkService.ASK).setSmallIcon(android.R.drawable.ic_dialog_info).setContentTitle("«$who» pide:")
            .setStyle(Notification.BigTextStyle().bigText(text)).setContentText(text).setAutoCancel(true).setTimeoutAfter(CONFIRM_S * 1000)
            .addAction(Notification.Action.Builder(null, "Permitir", pi(true)).build()).addAction(Notification.Action.Builder(null, "Rechazar", pi(false)).build()).build())
        latch.await(CONFIRM_S, TimeUnit.SECONDS)
        waiting.remove(mid)
        nm.cancel(mid.hashCode())
        return ok[0]
    }

    fun answer(id: String, allow: Boolean) {
        waiting[id]?.let { (latch, ok) -> ok[0] = allow; latch.countDown() }
    }
}

/** Mantiene vivo el vínculo (servicio en primer plano con un aviso fijo) para recibir órdenes y archivos con la app cerrada. */
class LinkService : Service() {
    private val answers = object : BroadcastReceiver() {
        override fun onReceive(c: Context, i: Intent) = Link.answer(i.getStringExtra("id") ?: "", i.getBooleanExtra("ok", false))
    }

    override fun onBind(i: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        val f = IntentFilter(ANSWER)
        if (Build.VERSION.SDK_INT >= 33) registerReceiver(answers, f, Context.RECEIVER_NOT_EXPORTED) else registerReceiver(answers, f)
    }

    override fun onStartCommand(i: Intent?, flags: Int, id: Int): Int {
        if (i?.action == STOP) { Link.stop(); stopSelf(); return START_NOT_STICKY }
        getSystemService(NotificationManager::class.java).createNotificationChannel(NotificationChannel(CHANNEL, "Vínculo con otro equipo", NotificationManager.IMPORTANCE_LOW))
        val stop = PendingIntent.getService(this, 4, Intent(this, LinkService::class.java).setAction(STOP), PendingIntent.FLAG_IMMUTABLE)
        val n = Notification.Builder(this, CHANNEL).setSmallIcon(android.R.drawable.stat_sys_data_bluetooth).setContentTitle("Fruquis está vinculado a otro equipo")
            .addAction(Notification.Action.Builder(null, "Detener", stop).build()).build()
        if (Build.VERSION.SDK_INT >= 34) startForeground(3, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE) else startForeground(3, n)
        Link.start(this)
        return START_STICKY
    }

    override fun onDestroy() {
        runCatching { unregisterReceiver(answers) }
        Link.stop()
        super.onDestroy()
    }

    companion object {
        const val STOP = "com.ojitos369.fruquis.LINK_STOP"
        const val ANSWER = "com.ojitos369.fruquis.LINK_ANSWER"
        const val CHANNEL = "link"
        const val ASK = "link_ask"
    }
}
