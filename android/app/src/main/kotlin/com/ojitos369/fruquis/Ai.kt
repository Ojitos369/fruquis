package com.ojitos369.fruquis

import android.content.SharedPreferences
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** IA por API (en Android no hay binarios): servidores oficiales (OpenAI, Anthropic) o uno propio con el mismo formato, cambiando la URL.
 *  Paridad con fruquis/provider.py (mismos valores por defecto y mismas rutas). Ajustes en SharedPreferences "ai": {chat,image}_{kind,url,key,model}.
 *  Las llamadas son bloqueantes: usarlas fuera del hilo principal. */
class Ai(val p: SharedPreferences) {
    private fun get(what: String, k: String) = p.getString("${what}_$k", "")!!.trim()

    /** Servidor propio aipi (claude/codex del servidor): POST {url}/api/chat/?key= y /api/image/?key=, imágenes en base64. */
    private fun server(what: String) = get(what, "kind") == "server"

    private fun anthropic(what: String) = what == "chat" && get(what, "kind") == "anthropic"

    private fun url(what: String) =
        get(what, "url").ifEmpty { if (anthropic(what)) ANTHROPIC else OPENAI }.trimEnd('/')

    private fun model(what: String) = get(what, "model").ifEmpty {
        when {
            server(what) -> ""
            what == "image" -> "gpt-image-1"
            anthropic(what) -> "claude-haiku-5-5"
            else -> "gpt-4o-mini"
        }
    }

    private fun post(what: String, path: String, body: JSONObject, readMs: Int = 120000): JSONObject {
        val key = get(what, "key")
        if (get(what, "url").isEmpty() && (key.isEmpty() || server(what))) throw Exception("Falta la ${if (server(what)) "URL del servidor" else "clave de la API"} (Ajustes IA).")
        var full = url(what) + path
        if (server(what)) {  // la URL de Ajustes es el enlace personal (con ?key=); también vale la base + clave aparte
            if ("/api/" in url(what)) full = url(what)
            if ("key=" !in full && key.isNotEmpty()) full += (if ("?" in full) "&" else "?") + "key=" + java.net.URLEncoder.encode(key, "UTF-8")
            if ("key=" !in full) throw Exception("Falta el enlace del servidor con su clave (Ajustes IA).")
        }
        val c = URL(full).openConnection() as HttpURLConnection
        c.requestMethod = "POST"
        c.connectTimeout = 15000
        c.readTimeout = readMs
        c.doOutput = true
        c.setRequestProperty("Content-Type", "application/json")
        c.setRequestProperty("User-Agent", "fruquis-android")
        if (key.isNotEmpty() && !server(what)) {
            if (anthropic(what)) {
                c.setRequestProperty("x-api-key", key)
                c.setRequestProperty("anthropic-version", "2023-06-01")
            } else c.setRequestProperty("Authorization", "Bearer $key")
        }
        c.outputStream.use { it.write(body.toString().toByteArray()) }
        val code = c.responseCode
        val text = (if (code < 400) c.inputStream else c.errorStream)?.use { it.readBytes().decodeToString() } ?: ""
        if (code >= 400) throw Exception("HTTP $code: ${text.take(300)}")
        return JSONObject(text)
    }

    private fun obj(vararg kv: Pair<String, Any>) = JSONObject().also { o -> kv.forEach { o.put(it.first, it.second) } }

    /** Respuesta de texto del chat; `jpegs` (opcional) = imágenes de referencia para visión. */
    fun chat(prompt: String, baseSystem: String, jpegs: List<ByteArray> = emptyList()): String {
        val system = baseSystem + Place.hint()
        val imgs = jpegs.map { Base64.encodeToString(it, Base64.NO_WRAP) }
        if (server("chat")) {
            val body = obj("prompt" to prompt, "system" to system, "images" to JSONArray(imgs))
            model("chat").let { if (it.isNotEmpty()) body.put("model", it) }
            return post("chat", "/api/chat/", body, 200000).getString("text").trim()
        }
        val text = obj("type" to "text", "text" to prompt)
        if (anthropic("chat")) {
            val parts = JSONArray()
            imgs.forEach { parts.put(obj("type" to "image", "source" to obj("type" to "base64", "media_type" to "image/jpeg", "data" to it))) }
            parts.put(text)
            val c = post("chat", "/v1/messages", obj("model" to model("chat"), "max_tokens" to 2048, "system" to system,
                "messages" to JSONArray().put(obj("role" to "user", "content" to parts)))).getJSONArray("content")
            return (0 until c.length()).joinToString("") { c.getJSONObject(it).optString("text") }.trim()
        }
        val user: Any = if (imgs.isEmpty()) prompt else JSONArray().also { a ->
            imgs.forEach { a.put(obj("type" to "image_url", "image_url" to obj("url" to "data:image/jpeg;base64,$it"))) }
            a.put(text)
        }
        return post("chat", "/chat/completions", obj("model" to model("chat"),
            "messages" to JSONArray().put(obj("role" to "system", "content" to system)).put(obj("role" to "user", "content" to user))))
            .getJSONArray("choices").getJSONObject(0).getJSONObject("message").getString("content").trim()
    }

    /** PNG generado por la API de imágenes (formato OpenAI; sin imágenes de referencia por ahora: /images/generations). */
    fun image(prompt: String): ByteArray {
        if (server("image")) return Base64.decode(post("image", "/api/image/", obj("prompt" to prompt), 900000).getString("image"), Base64.DEFAULT)
        val d = post("image", "/images/generations", obj("model" to model("image"), "prompt" to prompt, "size" to "1024x1024", "n" to 1))
            .getJSONArray("data").getJSONObject(0)
        return if (d.has("b64_json")) Base64.decode(d.getString("b64_json"), Base64.DEFAULT) else URL(d.getString("url")).openStream().use { it.readBytes() }
    }

    companion object {
        const val OPENAI = "https://api.openai.com/v1"
        const val ANTHROPIC = "https://api.anthropic.com"
    }
}

/** Ubicación aproximada por IP (sin permisos), para que la IA sepa dónde está el usuario. Paridad con fruquis/place.py. Bloqueante. */
object Place {
    private var text = ""  // solo se guarda si se obtuvo; si falla, se reintenta en el siguiente mensaje

    fun hint(): String {
        if (text.isEmpty()) try {
            val c = URL("https://ipwho.is/").openConnection() as HttpURLConnection
            c.connectTimeout = 4000
            c.readTimeout = 4000
            val d = JSONObject(c.inputStream.use { it.readBytes().decodeToString() })
            if (d.optBoolean("success")) text = " El usuario está (ubicación aproximada por IP) en ${d.getString("city")}, ${d.getString("region")}, " +
                "${d.getString("country")}, zona horaria ${d.optJSONObject("timezone")?.optString("id") ?: "?"}. Úsalo para el clima, la hora y lo cercano " +
                "sin preguntarle la ciudad, salvo que él mencione otro lugar."
        } catch (_: Exception) {  // sin red o servicio caído: se responde sin ubicación
        }
        return text
    }
}
