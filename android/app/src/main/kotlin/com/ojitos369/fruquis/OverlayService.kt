package com.ojitos369.fruquis

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Canvas
import android.graphics.PixelFormat
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.provider.Settings
import android.util.DisplayMetrics
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.Toast
import java.io.File
import kotlin.math.hypot
import kotlin.random.Random

/** Mascota flotante sobre las demás apps (como los shimejis): camina por el piso, trepa las paredes, se agarra y se lanza con físicas, y al
 *  tocarla saluda. Ventana TYPE_APPLICATION_OVERLAY (permiso «Mostrar sobre otras apps») mantenida por un servicio en primer plano.
 *  Paridad con el escritorio (fruquis/app.py): mismas animaciones (running-*, climbing, dragged, falling, waving, idle). */
class OverlayService : Service() {
    private val h = Handler(Looper.getMainLooper())
    private val sp = Sprite()
    private lateinit var wm: WindowManager
    private lateinit var lp: WindowManager.LayoutParams
    private var view: PetView? = null
    private var density = 1f
    private var x = 0f
    private var y = 0f
    private var vx = 0f
    private var vy = 0f
    private var rot = 0f
    private var size = 0
    private var state = IDLE
    private var dir = 1
    private var side = 0  // -1 pared izquierda, 1 derecha
    private var until = 0L
    private var last = 0L
    private var anim = ""

    override fun onBind(i: Intent?): IBinder? = null

    override fun onStartCommand(i: Intent?, flags: Int, id: Int): Int {
        if (i?.action == STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        startInForeground()
        if (view == null) {
            if (!Settings.canDrawOverlays(this) || !sp.load(File(filesDir, "character")) || !sp.ok) {
                Toast.makeText(this, "Falta el permiso de superposición o importar un personaje", Toast.LENGTH_LONG).show()
                stopSelf()
                return START_NOT_STICKY
            }
            create()
        }
        return START_NOT_STICKY
    }

    private fun startInForeground() {
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CHANNEL, "Mascota flotante", NotificationManager.IMPORTANCE_LOW))
        val stop = PendingIntent.getService(this, 0, Intent(this, OverlayService::class.java).setAction(STOP), PendingIntent.FLAG_IMMUTABLE)
        val n = Notification.Builder(this, CHANNEL).setSmallIcon(android.R.drawable.ic_menu_gallery).setContentTitle("Fruquis está flotando")
            .setContentText("Toca para quitarla de la pantalla").setContentIntent(stop)
            .addAction(android.R.drawable.ic_menu_close_clear_cancel, "Quitar", stop).build()
        if (Build.VERSION.SDK_INT >= 34) startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE) else startForeground(1, n)
    }

    private fun create() {
        running = true
        wm = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        density = resources.displayMetrics.density
        size = (SIZE_DP * density).toInt()
        lp = WindowManager.LayoutParams(size, size, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT).apply { gravity = Gravity.TOP or Gravity.LEFT }
        val v = PetView()
        view = v
        x = screen().widthPixels / 2f
        setState(FALL, 0)  // aparece cayendo desde arriba
        lp.x = x.toInt()
        lp.y = y.toInt()
        wm.addView(v, lp)
        last = System.currentTimeMillis()
        h.post(::tick)
    }

    private fun screen() = DisplayMetrics().also { wm.defaultDisplay.getRealMetrics(it) }

    private fun floor(): Float {  // y del piso: encima de la barra de navegación
        val id = resources.getIdentifier("navigation_bar_height", "dimen", "android")
        return screen().heightPixels - size - (if (id > 0) resources.getDimensionPixelSize(id) else 0).toFloat()
    }

    private fun setState(s: Int, ms: Long) {
        state = s
        until = System.currentTimeMillis() + ms
        rot = if (s == WALL) (if (side < 0) 90f else -90f) else 0f  // pies contra la pared
        anim = when (s) {
            WALK -> if (dir > 0) "running-right" else "running-left"
            WALL -> "climbing"
            FALL -> "falling"
            DRAG -> "dragged"
            else -> if (anim == "waving" && ms > 0) "waving" else "idle"
        }
        sp.start(anim)
    }

    private fun next() {  // qué hacer después de descansar o de caminar
        val r = Random.nextInt(10)
        when {
            r < 6 -> { dir = if (Random.nextBoolean()) 1 else -1; setState(WALK, 2000L + Random.nextInt(4000)) }
            r < 8 -> { anim = "waving"; setState(IDLE, 2000) }
            else -> { anim = ""; setState(IDLE, 1500L + Random.nextInt(3000)) }
        }
    }

    private fun tick() {
        val v = view ?: return
        val now = System.currentTimeMillis()
        val dt = minOf(0.05f, (now - last) / 1000f)
        last = now
        val w = (screen().widthPixels - size).toFloat()
        val fl = floor()
        when (state) {
            IDLE -> { y = fl; if (now > until) next() }
            WALK -> {
                x += dir * SPEED_DP * density * dt
                y = fl
                if (x <= 0 || x >= w) {
                    x = x.coerceIn(0f, w)
                    side = if (x <= 0) -1 else 1
                    if (Random.nextBoolean()) setState(WALL, 2000L + Random.nextInt(3000))
                    else { dir = -dir; setState(WALK, 2000L + Random.nextInt(4000)) }
                } else if (now > until) next()
            }
            WALL -> {
                x = if (side < 0) 0f else w
                y -= CLIMB_DP * density * dt
                if (y <= 0 || now > until) { y = maxOf(0f, y); vx = 0f; vy = 0f; setState(FALL, 0) }
            }
            FALL -> {
                vy += GRAVITY_DP * density * dt
                x += vx * dt
                y += vy * dt
                if ((x <= 0 || x >= w) && y < fl) { side = if (x <= 0) -1 else 1; setState(WALL, 2000L + Random.nextInt(3000)) }  // se pega a la pared
                else if (y >= fl) { y = fl; vx = 0f; vy = 0f; anim = ""; setState(IDLE, 600) }
                x = x.coerceIn(0f, w)
            }
        }  // DRAG: lo mueve el dedo
        lp.x = x.toInt()
        lp.y = y.toInt()
        v.rotation = rot  // la vista (cuadrada) gira sobre su centro
        wm.updateViewLayout(v, lp)
        v.invalidate()
        h.postDelayed(::tick, 33)
    }

    override fun onDestroy() {
        h.removeCallbacksAndMessages(null)
        view?.let { wm.removeView(it) }
        view = null
        running = false
        super.onDestroy()
    }

    private inner class PetView : View(this@OverlayService) {
        private var offX = 0f
        private var offY = 0f
        private var lastX = 0f
        private var lastY = 0f
        private var mx = 0f
        private var my = 0f
        private var lastT = 0L
        private var dragging = false

        override fun onDraw(c: Canvas) {
            sp.draw(c, width, height)
        }

        override fun onTouchEvent(e: MotionEvent): Boolean {
            val rx = e.rawX
            val ry = e.rawY
            val now = System.currentTimeMillis()
            when (e.action) {
                MotionEvent.ACTION_DOWN -> { offX = rx - x; offY = ry - y; lastX = rx; lastY = ry; lastT = now; mx = 0f; my = 0f; dragging = false }
                MotionEvent.ACTION_MOVE -> {
                    if (!dragging && hypot(rx - (x + offX), ry - (y + offY)) > 12 * density) { dragging = true; setState(DRAG, 0) }
                    if (dragging) {
                        val dtm = maxOf(1L, now - lastT) / 1000f
                        mx = 0.5f * mx + 0.5f * (rx - lastX) / dtm  // velocidad del dedo (suavizada) para el lanzamiento
                        my = 0.5f * my + 0.5f * (ry - lastY) / dtm
                        lastX = rx; lastY = ry; lastT = now
                        x = rx - offX
                        y = ry - offY
                    }
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    if (dragging) {
                        val cap = 2500 * density
                        val stale = now - lastT > 100
                        vx = (if (stale) 0f else mx).coerceIn(-cap, cap)
                        vy = (if (stale) 0f else my).coerceIn(-cap, cap)
                        setState(FALL, 0)
                    } else if (e.action == MotionEvent.ACTION_UP) {
                        anim = "waving"
                        setState(IDLE, 2000)
                    }
                }
                else -> return false
            }
            return true
        }
    }

    companion object {
        const val STOP = "com.ojitos369.fruquis.STOP"
        const val CHANNEL = "pet"
        @Volatile var running = false
        private const val IDLE = 0
        private const val WALK = 1
        private const val WALL = 2
        private const val FALL = 3
        private const val DRAG = 4
        private const val SIZE_DP = 120f
        private const val SPEED_DP = 60f
        private const val CLIMB_DP = 70f
        private const val GRAVITY_DP = 1400f
    }
}
