package com.ojitos369.fruquis;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Rect;

import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.util.HashMap;
import java.util.Map;

/** Personaje y animación actual, compartidos por la pantalla principal y la mascota flotante. Mismo formato que fruquis/sprites.py:
 *  character.json con cell [w,h] y anims {nombre: {sheet,row,frames,fps,loop,pingpong}}; el cuadro i está en (i % cols, row + i / cols). */
class Sprite {
    // animación de respaldo si el personaje no la trae (igual que sprites.WANTED)
    static final Map<String, String> FALLBACK = new HashMap<>();
    static {
        FALLBACK.put("eating", "waving"); FALLBACK.put("cleaning", "waving"); FALLBACK.put("pampered", "waving"); FALLBACK.put("talking", "waving");
        FALLBACK.put("playing", "jumping"); FALLBACK.put("sleeping", "waiting"); FALLBACK.put("sitting", "idle"); FALLBACK.put("dragged", "waiting");
        FALLBACK.put("falling", "jumping"); FALLBACK.put("climbing", "running-right"); FALLBACK.put("waving", "idle"); FALLBACK.put("jumping", "idle");
        FALLBACK.put("waiting", "idle");
    }

    File dir;
    JSONObject anims;
    Bitmap sheet;
    String sheetName = "";
    int cw = 192, ch = 208, row, frames = 1, fps = 8;
    boolean pingpong, loop;
    long t0;

    boolean ok() { return anims != null; }

    boolean load(File dir) {
        this.dir = dir;
        anims = null;
        sheetName = "";
        try (FileInputStream in = new FileInputStream(new File(dir, "character.json"))) {
            JSONObject j = new JSONObject(new String(readAll(in), "UTF-8"));
            if (j.has("cell")) { cw = j.getJSONArray("cell").getInt(0); ch = j.getJSONArray("cell").getInt(1); }
            anims = j.getJSONObject("anims");
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    static byte[] readAll(java.io.InputStream in) throws java.io.IOException {
        java.io.ByteArrayOutputStream o = new java.io.ByteArrayOutputStream();
        byte[] b = new byte[8192];
        for (int r; (r = in.read(b)) > 0; ) o.write(b, 0, r);
        return o.toByteArray();
    }

    /** Cambia de animación (con respaldos) y la reinicia. */
    void start(String name) {
        if (anims == null) return;
        try {
            String n = name;
            while (!anims.has(n) && FALLBACK.containsKey(n)) n = FALLBACK.get(n);
            if (!anims.has(n)) n = "idle";
            JSONObject a = anims.getJSONObject(n);
            String sh = a.getString("sheet");
            if (!sh.equals(sheetName)) {
                sheet = BitmapFactory.decodeFile(new File(dir, new File(sh).getName()).getPath());
                sheetName = sh;
            }
            row = a.getInt("row"); frames = Math.max(1, a.getInt("frames")); fps = Math.max(1, a.optInt("fps", 8));
            pingpong = a.optBoolean("pingpong"); loop = a.optBoolean("loop", true);
            t0 = System.currentTimeMillis();
        } catch (Exception e) {
            sheet = null;
        }
    }

    /** Dibuja el cuadro que toca en `dst`, conservando la proporción y apoyado abajo y centrado. */
    void draw(Canvas c, int w, int h) {
        if (sheet == null) return;
        int i = (int) ((System.currentTimeMillis() - t0) * fps / 1000);
        int n = pingpong && frames > 1 ? 2 * frames - 2 : frames;
        int k = loop ? i % n : Math.min(i, n - 1);
        if (k >= frames) k = n - k;
        int cols = Math.max(1, sheet.getWidth() / cw);
        int sx = (k % cols) * cw, sy = (row + k / cols) * ch;
        if (sx + cw > sheet.getWidth() || sy + ch > sheet.getHeight()) return;
        float s = Math.min(w / (float) cw, h / (float) ch);
        int dw = (int) (cw * s), dh = (int) (ch * s), x = (w - dw) / 2, y = h - dh;
        c.drawBitmap(sheet, new Rect(sx, sy, sx + cw, sy + ch), new Rect(x, y, x + dw, y + dh), null);
    }
}
