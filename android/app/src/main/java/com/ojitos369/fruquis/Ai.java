package com.ojitos369.fruquis;

import android.content.SharedPreferences;
import android.util.Base64;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/** IA por API (en Android no hay binarios): servidores oficiales (OpenAI, Anthropic) o uno propio con el mismo formato, cambiando la URL.
 *  Paridad con fruquis/provider.py (mismos valores por defecto y mismas rutas). Ajustes en SharedPreferences "ai": {chat,image}_{kind,url,key,model}.
 *  Las llamadas son bloqueantes: usarlas fuera del hilo principal. */
public class Ai {
    static final String OPENAI = "https://api.openai.com/v1", ANTHROPIC = "https://api.anthropic.com";
    final SharedPreferences p;

    public Ai(SharedPreferences p) { this.p = p; }

    String get(String what, String k) { return p.getString(what + "_" + k, "").trim(); }

    public void set(String what, String kind, String url, String key, String model) {
        p.edit().putString(what + "_kind", kind).putString(what + "_url", url).putString(what + "_key", key).putString(what + "_model", model).apply();
    }

    public boolean anthropic(String what) { return what.equals("chat") && get(what, "kind").equals("anthropic"); }

    String url(String what) {
        String u = get(what, "url");
        return (u.isEmpty() ? (anthropic(what) ? ANTHROPIC : OPENAI) : u).replaceAll("/+$", "");
    }

    String model(String what) {
        String m = get(what, "model");
        return !m.isEmpty() ? m : what.equals("image") ? "gpt-image-1" : anthropic(what) ? "claude-haiku-5-5" : "gpt-4o-mini";
    }

    JSONObject post(String what, String path, String contentType, byte[] body) throws Exception {
        boolean official = get(what, "url").isEmpty(), a = anthropic(what);
        String key = get(what, "key");
        if (official && key.isEmpty()) throw new Exception("Falta la clave de la API (Ajustes IA).");
        HttpURLConnection c = (HttpURLConnection) new URL(url(what) + path).openConnection();
        c.setRequestMethod("POST");
        c.setConnectTimeout(15000);
        c.setReadTimeout(120000);
        c.setDoOutput(true);
        c.setRequestProperty("Content-Type", contentType);
        if (!key.isEmpty()) {
            if (a) { c.setRequestProperty("x-api-key", key); c.setRequestProperty("anthropic-version", "2023-06-01"); }
            else c.setRequestProperty("Authorization", "Bearer " + key);
        }
        try (OutputStream o = c.getOutputStream()) { o.write(body); }
        int code = c.getResponseCode();
        InputStream in = code < 400 ? c.getInputStream() : c.getErrorStream();
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        for (int r; in != null && (r = in.read(buf)) > 0; ) out.write(buf, 0, r);
        if (code >= 400) throw new Exception("HTTP " + code + ": " + out.toString("UTF-8").substring(0, Math.min(300, out.size())));
        return new JSONObject(out.toString("UTF-8"));
    }

    /** Respuesta de texto del chat; `png` (opcional) = imagen para visión. */
    public String chat(String prompt, String system, byte[] png) throws Exception {
        String img = png == null ? null : Base64.encodeToString(png, Base64.NO_WRAP);
        JSONObject b = new JSONObject().put("model", model("chat"));
        if (anthropic("chat")) {
            JSONArray parts = new JSONArray();
            if (img != null) parts.put(new JSONObject().put("type", "image").put("source", new JSONObject().put("type", "base64").put("media_type", "image/png").put("data", img)));
            parts.put(new JSONObject().put("type", "text").put("text", prompt));
            b.put("max_tokens", 2048).put("system", system).put("messages", new JSONArray().put(new JSONObject().put("role", "user").put("content", parts)));
            JSONArray c = post("chat", "/v1/messages", "application/json", b.toString().getBytes("UTF-8")).getJSONArray("content");
            StringBuilder s = new StringBuilder();
            for (int i = 0; i < c.length(); i++) s.append(c.getJSONObject(i).optString("text"));
            return s.toString().trim();
        }
        JSONArray parts = new JSONArray();
        if (img != null) parts.put(new JSONObject().put("type", "image_url").put("image_url", new JSONObject().put("url", "data:image/png;base64," + img)));
        parts.put(new JSONObject().put("type", "text").put("text", prompt));
        b.put("messages", new JSONArray().put(new JSONObject().put("role", "system").put("content", system))
                .put(new JSONObject().put("role", "user").put("content", img == null ? prompt : parts)));
        return post("chat", "/chat/completions", "application/json", b.toString().getBytes("UTF-8"))
                .getJSONArray("choices").getJSONObject(0).getJSONObject("message").getString("content").trim();
    }

    /** PNG generado por la API de imágenes (formato OpenAI; sin imágenes de referencia por ahora: /images/generations). */
    public byte[] image(String prompt) throws Exception {
        JSONObject b = new JSONObject().put("model", model("image")).put("prompt", prompt).put("size", "1024x1024").put("n", 1);
        JSONObject d = post("image", "/images/generations", "application/json", b.toString().getBytes("UTF-8")).getJSONArray("data").getJSONObject(0);
        if (d.has("b64_json")) return Base64.decode(d.getString("b64_json"), Base64.DEFAULT);
        try (InputStream in = new URL(d.getString("url")).openStream(); ByteArrayOutputStream o = new ByteArrayOutputStream()) {
            byte[] buf = new byte[8192];
            for (int r; (r = in.read(buf)) > 0; ) o.write(buf, 0, r);
            return o.toByteArray();
        }
    }
}
