package com.ojitos369.fruquis;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Rect;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.util.HashMap;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/** Versión Android de Fruquis: la mascota animada con las mismas hojas de sprites (character.json) y el mismo tamagotchi que el escritorio.
 *  Mantener en paridad con fruquis/care.py (valores de DECAY/FLOOR/ACTIONS) y con el formato de fruquis/sprites.py. */
public class MainActivity extends Activity {
    // hambre, limpieza, diversion, energia -> puntos por hora (igual que care.DECAY)
    static final String[] KEYS = {"hambre", "limpieza", "diversion", "energia"};
    static final double[] DECAY = {6, 4, 5, 2};
    static final double FLOOR = 15;
    // acción: {animación, hambre, limpieza, diversion, energia} (igual que care.ACTIONS)
    static final String[][] ACTIONS = {
        {"Comer", "eating", "35", "-5", "0", "0"}, {"Limpiar", "cleaning", "0", "50", "0", "0"},
        {"Jugar", "playing", "-5", "0", "30", "-8"}, {"Mimar", "pampered", "0", "0", "25", "3"},
        {"Dormir", "sleeping", "-3", "0", "0", "40"}};
    // animación de respaldo si el personaje no la trae (igual que sprites.WANTED)
    static final Map<String, String> FALLBACK = new HashMap<>();
    static {
        FALLBACK.put("eating", "waving"); FALLBACK.put("cleaning", "waving"); FALLBACK.put("pampered", "waving");
        FALLBACK.put("playing", "jumping"); FALLBACK.put("sleeping", "waiting"); FALLBACK.put("waving", "idle");
        FALLBACK.put("jumping", "idle"); FALLBACK.put("waiting", "idle");
    }

    final Handler h = new Handler(Looper.getMainLooper());
    SharedPreferences prefs;
    double[] stats = new double[4];
    PetView pet;
    TextView status;
    String current = "idle";
    long until;

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        prefs = getSharedPreferences("care", MODE_PRIVATE);
        loadCare();
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(24, 48, 24, 24);
        pet = new PetView();
        root.addView(pet, new LinearLayout.LayoutParams(-1, 0, 1));
        status = new TextView(this);
        status.setGravity(Gravity.CENTER);
        root.addView(status);
        LinearLayout row = new LinearLayout(this);
        for (String[] a : ACTIONS) {
            Button bt = new Button(this);
            bt.setText(a[0]);
            bt.setAllCaps(false);
            bt.setOnClickListener(v -> act(a));
            row.addView(bt, new LinearLayout.LayoutParams(0, -2, 1));
        }
        root.addView(row);
        Button imp = new Button(this);
        imp.setText("Importar personaje (.zip)");
        imp.setOnClickListener(v -> startActivityForResult(new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("*/*").addCategory(Intent.CATEGORY_OPENABLE), 1));
        root.addView(imp);
        setContentView(root);
        pet.setOnClickListener(v -> play("waving", 2000));
        pet.load();
        tick();
    }

    @Override protected void onActivityResult(int req, int res, Intent data) {
        if (req != 1 || res != RESULT_OK || data == null) return;
        try (InputStream in = getContentResolver().openInputStream(data.getData())) {
            importZip(in);
            pet.load();
            Toast.makeText(this, pet.ok() ? "Personaje importado" : "El zip no trae character.json", Toast.LENGTH_LONG).show();
        } catch (Exception e) {
            Toast.makeText(this, "No se pudo importar: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    File dir() { return new File(getFilesDir(), "character"); }

    /** Extrae solo .json/.png/.md y por nombre de archivo (el zip trae <id>/<archivo>): no hay rutas que escapen de la carpeta. */
    void importZip(InputStream in) throws Exception {
        File tmp = new File(getFilesDir(), "character.tmp");
        deleteAll(tmp);
        tmp.mkdirs();
        try (ZipInputStream z = new ZipInputStream(in)) {
            long total = 0;
            for (ZipEntry e; (e = z.getNextEntry()) != null; ) {
                String n = new File(e.getName()).getName();
                if (e.isDirectory() || !n.matches("[\\w.\\- ]+\\.(json|png|md)")) continue;
                try (FileOutputStream o = new FileOutputStream(new File(tmp, n))) {
                    byte[] buf = new byte[8192];
                    for (int r; (r = z.read(buf)) > 0; ) {
                        if ((total += r) > 200L << 20) throw new Exception("zip demasiado grande");
                        o.write(buf, 0, r);
                    }
                }
            }
        }
        if (!new File(tmp, "character.json").exists()) { deleteAll(tmp); throw new Exception("falta character.json"); }
        deleteAll(dir());
        if (!tmp.renameTo(dir())) throw new Exception("no se pudo guardar");
    }

    static void deleteAll(File f) {
        File[] c = f.listFiles();
        if (c != null) for (File x : c) deleteAll(x);
        f.delete();
    }

    // ---- tamagotchi (care.py) ----
    void loadCare() {
        long at = prefs.getLong("at", System.currentTimeMillis());
        for (int i = 0; i < 4; i++) stats[i] = prefs.getFloat(KEYS[i], 80);
        advance((System.currentTimeMillis() - at) / 1000.0, true);
    }

    void advance(double seconds, boolean offline) {
        for (int i = 0; i < 4; i++) {
            double v = stats[i] - DECAY[i] * seconds / 3600;
            stats[i] = offline ? Math.max(Math.min(stats[i], FLOOR), v) : Math.max(0, v);
        }
        saveCare();
    }

    void saveCare() {
        SharedPreferences.Editor e = prefs.edit().putLong("at", System.currentTimeMillis());
        for (int i = 0; i < 4; i++) e.putFloat(KEYS[i], (float) stats[i]);
        e.apply();
    }

    void act(String[] a) {
        for (int i = 0; i < 4; i++) stats[i] = Math.min(100, Math.max(0, stats[i] + Integer.parseInt(a[2 + i])));
        saveCare();
        play(a[1], 3000);
    }

    void play(String anim, long ms) {
        current = anim;
        until = System.currentTimeMillis() + ms;
        pet.start(anim);
        showStatus();
    }

    void showStatus() {
        status.setText(String.format("🍙 %d   🫧 %d   🎾 %d   ⚡ %d", (int) stats[0], (int) stats[1], (int) stats[2], (int) stats[3]));
    }

    void tick() {
        advance(60, false);
        showStatus();
        h.postDelayed(this::tick, 60000);
    }

    @Override protected void onResume() { super.onResume(); loadCare(); showStatus(); pet.start(current); }
    @Override protected void onDestroy() { h.removeCallbacksAndMessages(null); super.onDestroy(); }

    // ---- sprites (sprites.py / app.py) ----
    class PetView extends View {
        JSONObject anims;
        Bitmap sheet;
        String sheetName = "";
        int cw = 192, ch = 208, row, frames = 1, fps = 8, i;
        boolean pingpong, loop;
        final Runnable step = new Runnable() {
            @Override public void run() {
                if (anims == null) return;
                i++;
                if (until > 0 && System.currentTimeMillis() > until && !current.equals("idle")) { current = "idle"; until = 0; start("idle"); return; }
                invalidate();
                postDelayed(this, 1000 / Math.max(1, fps));
            }
        };

        PetView() { super(MainActivity.this); }

        boolean ok() { return anims != null; }

        void load() {
            anims = null;
            try {
                JSONObject j = new JSONObject(new String(java.nio.file.Files.readAllBytes(new File(dir(), "character.json").toPath())));
                if (j.has("cell")) { cw = j.getJSONArray("cell").getInt(0); ch = j.getJSONArray("cell").getInt(1); }
                anims = j.getJSONObject("anims");
                start(current);
            } catch (Exception e) {
                invalidate();
            }
        }

        void start(String name) {
            removeCallbacks(step);
            if (anims == null) return;
            try {
                String n = name;
                while (!anims.has(n) && FALLBACK.containsKey(n)) n = FALLBACK.get(n);
                if (!anims.has(n)) n = "idle";
                JSONObject a = anims.getJSONObject(n);
                if (!a.getString("sheet").equals(sheetName)) {
                    sheet = BitmapFactory.decodeFile(new File(dir(), new File(a.getString("sheet")).getName()).getPath());
                    sheetName = a.getString("sheet");
                }
                row = a.getInt("row"); frames = Math.max(1, a.getInt("frames")); fps = a.optInt("fps", 8);
                pingpong = a.optBoolean("pingpong"); loop = a.optBoolean("loop", true); i = 0;
                post(step);
            } catch (Exception e) {
                sheet = null;
                invalidate();
            }
        }

        @Override protected void onDraw(Canvas c) {
            if (sheet == null) return;
            int n = pingpong && frames > 1 ? 2 * frames - 2 : frames;
            int k = loop ? i % n : Math.min(i, n - 1);
            if (k >= frames) k = n - k;
            int cols = Math.max(1, sheet.getWidth() / cw);
            int sx = (k % cols) * cw, sy = (row + k / cols) * ch;
            if (sx + cw > sheet.getWidth() || sy + ch > sheet.getHeight()) return;
            float s = Math.min(getWidth() / (float) cw, getHeight() / (float) ch);
            int w = (int) (cw * s), hh = (int) (ch * s);
            int x = (getWidth() - w) / 2, y = getHeight() - hh;
            c.drawBitmap(sheet, new Rect(sx, sy, sx + cw, sy + ch), new Rect(x, y, x + w, y + hh), null);
        }
    }
}
