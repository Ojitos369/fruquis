package com.ojitos369.fruquis;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;
import android.provider.Settings;
import android.graphics.Canvas;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.text.InputType;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;


import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
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
    final Handler h = new Handler(Looper.getMainLooper());
    SharedPreferences prefs;
    double[] stats = new double[4];
    PetView pet;
    Button floatBtn;
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
        floatBtn = new Button(this);
        floatBtn.setOnClickListener(v -> toggleFloat());
        root.addView(floatBtn);
        LinearLayout ai = new LinearLayout(this);
        Button talk = new Button(this), cfg = new Button(this);
        talk.setText("Hablar");
        talk.setOnClickListener(v -> talkDialog());
        cfg.setText("Ajustes de IA");
        cfg.setOnClickListener(v -> aiDialog());
        ai.addView(talk, new LinearLayout.LayoutParams(0, -2, 1));
        ai.addView(cfg, new LinearLayout.LayoutParams(0, -2, 1));
        root.addView(ai);
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

    // ---- IA por API (Ai.java / provider.py) ----
    void talkDialog() {
        EditText t = new EditText(this);
        new AlertDialog.Builder(this).setTitle("Dile algo").setView(t).setNegativeButton("Cancelar", null).setPositiveButton("Enviar", (d, w) -> {
            play("talking", 120000);
            new Thread(() -> {
                String r;
                try {
                    r = new Ai(getSharedPreferences("ai", MODE_PRIVATE)).chat(t.getText().toString(),
                        "Eres Fruquis, una mascota tierna. Responde siempre en español, máximo 3 frases.", null);
                } catch (Exception e) {
                    r = "No pude responder (" + e.getMessage() + ")";
                }
                String out = r;
                runOnUiThread(() -> { until = System.currentTimeMillis() + 2000; status.setText(out); });
            }).start();
        }).show();
    }

    void aiDialog() {
        Ai ai = new Ai(getSharedPreferences("ai", MODE_PRIVATE));
        LinearLayout l = new LinearLayout(this);
        l.setOrientation(LinearLayout.VERTICAL);
        l.setPadding(32, 16, 32, 0);
        String[][] f = {{"chat", "kind", "Chat: formato (openai | anthropic)"}, {"chat", "url", "Chat: URL base (vacío = oficial)"}, {"chat", "key", "Chat: clave"},
            {"chat", "model", "Chat: modelo (vacío = predeterminado)"}, {"image", "url", "Imágenes: URL base (vacío = OpenAI)"}, {"image", "key", "Imágenes: clave"},
            {"image", "model", "Imágenes: modelo (vacío = gpt-image-1)"}};
        EditText[] e = new EditText[f.length];
        for (int i = 0; i < f.length; i++) {
            e[i] = new EditText(this);
            e[i].setHint(f[i][2]);
            e[i].setText(ai.p.getString(f[i][0] + "_" + f[i][1], ""));
            e[i].setSingleLine();
            if (f[i][1].equals("key")) e[i].setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
            l.addView(e[i]);
        }
        new AlertDialog.Builder(this).setTitle("IA por API").setView(l).setNegativeButton("Cancelar", null).setPositiveButton("Guardar", (d, w) -> {
            SharedPreferences.Editor ed = ai.p.edit();
            for (int i = 0; i < f.length; i++) ed.putString(f[i][0] + "_" + f[i][1], e[i].getText().toString().trim());
            ed.apply();
        }).show();
    }

    // ---- mascota flotante (OverlayService) ----
    void toggleFloat() {
        if (OverlayService.running) {
            startService(new Intent(this, OverlayService.class).setAction(OverlayService.STOP));
            floatBtn.postDelayed(this::showFloat, 300);
            return;
        }
        if (!pet.ok()) { Toast.makeText(this, "Importa primero un personaje", Toast.LENGTH_LONG).show(); return; }
        if (!Settings.canDrawOverlays(this)) {  // permiso especial «Mostrar sobre otras apps»: se concede en una pantalla de Ajustes
            Toast.makeText(this, "Activa «Mostrar sobre otras apps» para Fruquis y vuelve", Toast.LENGTH_LONG).show();
            startActivity(new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:" + getPackageName())));
            return;
        }
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission("android.permission.POST_NOTIFICATIONS") != PackageManager.PERMISSION_GRANTED)
            requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, 2);  // para ver el aviso con el botón «Quitar»
        startForegroundService(new Intent(this, OverlayService.class));
        floatBtn.postDelayed(this::showFloat, 500);
    }

    void showFloat() { floatBtn.setText(OverlayService.running ? "Quitar mascota flotante" : "Mascota flotante"); }

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

    @Override protected void onResume() { super.onResume(); showFloat(); loadCare(); showStatus(); pet.start(current); }
    @Override protected void onDestroy() { h.removeCallbacksAndMessages(null); super.onDestroy(); }

    // ---- sprites (Sprite.java) ----
    class PetView extends View {
        final Sprite sp = new Sprite();
        final Runnable step = new Runnable() {
            @Override public void run() {
                if (until > 0 && System.currentTimeMillis() > until && !current.equals("idle")) { current = "idle"; until = 0; sp.start("idle"); }
                invalidate();
                postDelayed(this, 1000 / sp.fps);
            }
        };

        PetView() { super(MainActivity.this); }

        boolean ok() { return sp.ok(); }

        void load() {
            removeCallbacks(step);
            if (sp.load(dir())) start(current); else invalidate();
        }

        void start(String name) {
            removeCallbacks(step);
            if (!sp.ok()) return;
            sp.start(name);
            post(step);
        }

        @Override protected void onDraw(Canvas c) { sp.draw(c, getWidth(), getHeight()); }
    }
}
