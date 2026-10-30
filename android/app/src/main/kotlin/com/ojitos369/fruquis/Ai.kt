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

    private fun anthropic(what: String) = what == "chat" && get(what, "kind") == "anthropic"

    private fun url(what: String) =
        get(what, "url").ifEmpty { if (anthropic(what)) ANTHROPIC else OPENAI }.trimEnd('/')

    private fun model(what: String) = get(what, "model").ifEmpty {
        when {
            what == "image" -> "gpt-image-1"
            anthropic(what) -> "claude-haiku-5-5"
            else -> "gpt-4o-mini"
        }
    }

    private fun post(what: String, path: String, body: JSONObject): JSONObject {
        val key = get(what, "key")
        if (get(what, "url").isEmpty() && key.isEmpty()) throw Exception("Falta la clave de la API (Ajustes IA).")
        val c = URL(url(what) + path).openConnection() as HttpURLConnection
        c.requestMethod = "POST"
        c.connectTimeout = 15000
        c.readTimeout = 120000
        c.doOutput = true
        c.setRequestProperty("Content-Type", "application/json")
        if (key.isNotEmpty()) {
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

    /** Respuesta de texto del chat; `png` (opcional) = imagen para visión. */
    fun chat(prompt: String, system: String, png: ByteArray? = null): String {
        val img = png?.let { Base64.encodeToString(it, Base64.NO_WRAP) }
        val text = obj("type" to "text", "text" to prompt)
        if (anthropic("chat")) {
            val parts = JSONArray()
            if (img != null) parts.put(obj("type" to "image", "source" to obj("type" to "base64", "media_type" to "image/png", "data" to img)))
            parts.put(text)
            val c = post("chat", "/v1/messages", obj("model" to model("chat"), "max_tokens" to 2048, "system" to system,
                "messages" to JSONArray().put(obj("role" to "user", "content" to parts)))).getJSONArray("content")
            return (0 until c.length()).joinToString("") { c.getJSONObject(it).optString("text") }.trim()
        }
        val user: Any = if (img == null) prompt else JSONArray()
            .put(obj("type" to "image_url", "image_url" to obj("url" to "data:image/png;base64,$img"))).put(text)
        return post("chat", "/chat/completions", obj("model" to model("chat"),
            "messages" to JSONArray().put(obj("role" to "system", "content" to system)).put(obj("role" to "user", "content" to user))))
            .getJSONArray("choices").getJSONObject(0).getJSONObject("message").getString("content").trim()
    }

    /** PNG generado por la API de imágenes (formato OpenAI; sin imágenes de referencia por ahora: /images/generations). */
    fun image(prompt: String): ByteArray {
        val d = post("image", "/images/generations", obj("model" to model("image"), "prompt" to prompt, "size" to "1024x1024", "n" to 1))
            .getJSONArray("data").getJSONObject(0)
        return if (d.has("b64_json")) Base64.decode(d.getString("b64_json"), Base64.DEFAULT) else URL(d.getString("url")).openStream().use { it.readBytes() }
    }

    companion object {
        const val OPENAI = "https://api.openai.com/v1"
        const val ANTHROPIC = "https://api.anthropic.com"
    }
}
