package com.ojitos369.fruquis;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.graphics.Canvas;
import android.graphics.PixelFormat;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.provider.Settings;
import android.util.DisplayMetrics;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.widget.Toast;

import java.io.File;
import java.util.Random;

/** Mascota flotante sobre las demás apps (como los shimejis): camina por el piso, trepa las paredes, se agarra y se lanza con físicas, y al
 *  tocarla saluda. Ventana TYPE_APPLICATION_OVERLAY (permiso «Mostrar sobre otras apps») mantenida por un servicio en primer plano.
 *  Paridad con el escritorio (fruquis/app.py): mismas animaciones (running-*, climbing, dragged, falling, waving, idle). */
public class OverlayService extends Service {
    static final String STOP = "com.ojitos369.fruquis.STOP", CHANNEL = "pet";
    static boolean running;
    static final int IDLE = 0, WALK = 1, WALL = 2, FALL = 3, DRAG = 4;
    static final float SIZE_DP = 120, SPEED_DP = 60, CLIMB_DP = 70, GRAVITY_DP = 1400;

    final Handler h = new Handler(Looper.getMainLooper());
    final Random rnd = new Random();
    final Sprite sp = new Sprite();
    WindowManager wm;
    WindowManager.LayoutParams lp;
    PetView view;
    float density, x, y, vx, vy, rot;
    int size, state = IDLE, dir = 1, side;  // side: -1 pared izquierda, 1 derecha
    long until, last;
    String anim = "";

    @Override public IBinder onBind(Intent i) { return null; }

    @Override public int onStartCommand(Intent in, int flags, int id) {
        if (in != null && STOP.equals(in.getAction())) { stopSelf(); return START_NOT_STICKY; }
        startForeground();
        if (view == null) {
            if (!Settings.canDrawOverlays(this) || !sp.load(new File(getFilesDir(), "character")) || !sp.ok()) {
                Toast.makeText(this, "Falta el permiso de superposición o importar un personaje", Toast.LENGTH_LONG).show();
                stopSelf();
                return START_NOT_STICKY;
            }
            create();
        }
        return START_NOT_STICKY;
    }

    void startForeground() {
        NotificationManager nm = getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel(CHANNEL, "Mascota flotante", NotificationManager.IMPORTANCE_LOW));
        PendingIntent stop = PendingIntent.getService(this, 0, new Intent(this, OverlayService.class).setAction(STOP), PendingIntent.FLAG_IMMUTABLE);
        Notification n = new Notification.Builder(this, CHANNEL).setSmallIcon(android.R.drawable.ic_menu_gallery).setContentTitle("Fruquis está flotando")
            .setContentText("Toca para quitarla de la pantalla").setContentIntent(stop).addAction(android.R.drawable.ic_menu_close_clear_cancel, "Quitar", stop).build();
        if (Build.VERSION.SDK_INT >= 34) startForeground(1, n, android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        else startForeground(1, n);
    }

    void create() {
        running = true;
        wm = (WindowManager) getSystemService(Context.WINDOW_SERVICE);
        density = getResources().getDisplayMetrics().density;
        size = (int) (SIZE_DP * density);
        lp = new WindowManager.LayoutParams(size, size, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT);
        lp.gravity = Gravity.TOP | Gravity.LEFT;
        view = new PetView();
        x = screen().widthPixels / 2f;
        y = 0;
        setState(FALL, 0);  // aparece cayendo desde arriba
        lp.x = (int) x; lp.y = (int) y;
        wm.addView(view, lp);
        last = System.currentTimeMillis();
        h.post(this::tick);
    }

    DisplayMetrics screen() {
        DisplayMetrics m = new DisplayMetrics();
        wm.getDefaultDisplay().getRealMetrics(m);
        return m;
    }

    float floor() {  // y del piso: encima de la barra de navegación
        int id = getResources().getIdentifier("navigation_bar_height", "dimen", "android");
        return screen().heightPixels - size - (id > 0 ? getResources().getDimensionPixelSize(id) : 0);
    }

    void setState(int s, long ms) {
        state = s;
        until = System.currentTimeMillis() + ms;
        rot = s == WALL ? (side < 0 ? 90 : -90) : 0;  // pies contra la pared
        String a = s == WALK ? (dir > 0 ? "running-right" : "running-left") : s == WALL ? "climbing" : s == FALL ? "falling" : s == DRAG ? "dragged" : anim.equals("waving") && ms > 0 ? "waving" : "idle";
        play(a);
    }

    void play(String a) {
        anim = a;
        sp.start(a);
    }

    void next() {  // qué hacer después de descansar o de caminar
        int r = rnd.nextInt(10);
        if (r < 6) { dir = rnd.nextBoolean() ? 1 : -1; setState(WALK, 2000 + rnd.nextInt(4000)); }
        else if (r < 8) { anim = "waving"; setState(IDLE, 2000); }
        else { anim = ""; setState(IDLE, 1500 + rnd.nextInt(3000)); }
    }

    void tick() {
        if (view == null) return;
        long now = System.currentTimeMillis();
        float dt = Math.min(0.05f, (now - last) / 1000f);
        last = now;
        float w = screen().widthPixels - size, fl = floor();
        switch (state) {
            case IDLE:
                y = fl;
                if (now > until) next();
                break;
            case WALK:
                x += dir * SPEED_DP * density * dt;
                y = fl;
                if (x <= 0 || x >= w) {
                    x = Math.max(0, Math.min(w, x));
                    side = x <= 0 ? -1 : 1;
                    if (rnd.nextBoolean()) setState(WALL, 2000 + rnd.nextInt(3000));
                    else { dir = -dir; setState(WALK, 2000 + rnd.nextInt(4000)); }
                } else if (now > until) next();
                break;
            case WALL:
                x = side < 0 ? 0 : w;
                y -= CLIMB_DP * density * dt;
                if (y <= 0 || now > until) { y = Math.max(0, y); vx = vy = 0; setState(FALL, 0); }
                break;
            case FALL:
                vy += GRAVITY_DP * density * dt;
                x += vx * dt;
                y += vy * dt;
                if ((x <= 0 || x >= w) && y < fl) { side = x <= 0 ? -1 : 1; setState(WALL, 2000 + rnd.nextInt(3000)); }  // se pega a la pared
                else if (y >= fl) { y = fl; vx = vy = 0; anim = ""; setState(IDLE, 600); }
                x = Math.max(0, Math.min(w, x));
                break;
            default:  // DRAG: lo mueve el dedo
        }
        lp.x = (int) x; lp.y = (int) y;
        view.rotation = rot;
        wm.updateViewLayout(view, lp);
        view.invalidate();
        h.postDelayed(this::tick, 33);
    }

    @Override public void onDestroy() {
        h.removeCallbacksAndMessages(null);
        if (view != null) { wm.removeView(view); view = null; }
        running = false;
        super.onDestroy();
    }

    class PetView extends View {
        float rotation, offX, offY, lastX, lastY, mx, my;
        long lastT;
        boolean dragging;

        PetView() { super(OverlayService.this); }

        @Override protected void onDraw(Canvas c) {
            c.save();
            c.rotate(rotation, getWidth() / 2f, getHeight() / 2f);
            sp.draw(c, getWidth(), getHeight());
            c.restore();
        }

        @Override public boolean onTouchEvent(MotionEvent e) {
            float rx = e.getRawX(), ry = e.getRawY();
            long now = System.currentTimeMillis();
            switch (e.getAction()) {
                case MotionEvent.ACTION_DOWN:
                    offX = rx - x; offY = ry - y; lastX = rx; lastY = ry; lastT = now; mx = my = 0; dragging = false;
                    return true;
                case MotionEvent.ACTION_MOVE:
                    if (!dragging && Math.hypot(rx - (x + offX), ry - (y + offY)) > 12 * density) { dragging = true; setState(DRAG, 0); }
                    if (dragging) {
                        float dtm = Math.max(1, now - lastT) / 1000f;
                        mx = 0.5f * mx + 0.5f * (rx - lastX) / dtm;  // velocidad del dedo (suavizada) para el lanzamiento
                        my = 0.5f * my + 0.5f * (ry - lastY) / dtm;
                        lastX = rx; lastY = ry; lastT = now;
                        x = rx - offX; y = ry - offY;
                    }
                    return true;
                case MotionEvent.ACTION_UP:
                case MotionEvent.ACTION_CANCEL:
                    if (dragging) {
                        float cap = 2500 * density;
                        vx = Math.max(-cap, Math.min(cap, now - lastT > 100 ? 0 : mx));
                        vy = Math.max(-cap, Math.min(cap, now - lastT > 100 ? 0 : my));
                        setState(FALL, 0);
                    } else if (e.getAction() == MotionEvent.ACTION_UP) {
                        anim = "waving";
                        setState(IDLE, 2000);
                    }
                    return true;
            }
            return false;
        }
    }
}
