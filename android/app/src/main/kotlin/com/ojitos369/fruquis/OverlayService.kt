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
import android.widget.LinearLayout
import android.widget.TextView
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
    private var held = false  // dedo sobre la mascota
    private var listening = false
    private var freeSide = ""  // "left" | "right": lado del piso que se le pidió dejar libre
    private var freeFrac = 0.35f
    private val care by lazy { Care(getSharedPreferences("care", MODE_PRIVATE)) }
    private var menu: View? = null  // menú de acciones al tocarla (ventana propia)
    private var careAt = 0L
    private var lowAt = 0L

    override fun onBind(i: Intent?): IBinder? = null

    override fun onStartCommand(i: Intent?, flags: Int, id: Int): Int {
        if (i?.action == STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        if (i?.action == MOVE && view != null) {  // orden de voz: «muévete a la derecha»
            val w = (screen().widthPixels - size).toFloat()
            x = when (i.getStringExtra("side")) { "left" -> 0f; "right" -> w; else -> w / 2 }
            x = clampFree(x, w)
            y = floor()
            anim = "waving"
            setState(IDLE, 2000)
            return START_NOT_STICKY
        }
        if (i?.action == FREE && view != null) {  // «deja libre la derecha» (sin lado: vuelve a andar por donde quiera)
            val s = i.getStringExtra("side") ?: ""
            freeSide = if (s == "left" || s == "right") s else ""
            freeFrac = i.getFloatExtra("frac", 0.35f)
            val w = (screen().widthPixels - size).toFloat()
            x = clampFree(x, w)
            if (freeSide.isNotEmpty() && (state == WALL || state == CLING)) setState(FALL, 0)  // se suelta de la pared y cae al piso
            return START_NOT_STICKY
        }
        if (i?.action == RELOAD && view != null) {  // se eligió otro personaje en el catálogo
            if (sp.load(MainActivity.activeDir(this))) sp.start(anim)
            return START_NOT_STICKY
        }
        startInForeground()
        if (view == null) {
            if (!Settings.canDrawOverlays(this) || !sp.load(MainActivity.activeDir(this)) || !sp.ok) {
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
        // IN_SCREEN + NO_LIMITS + recorte de cámara: x/y son de la pantalla completa y el sistema no recorta la ventana contra las barras
        // (sin esto, al arrastrarla cerca de un borde la ventana se quedaba fija y el personaje salía cortado)
        lp = WindowManager.LayoutParams(size, size, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS or WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT).apply {
            gravity = Gravity.TOP or Gravity.LEFT
            if (Build.VERSION.SDK_INT >= 28) layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
        }
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

    // medidas en caché: leerlas en cada tick (llamada al sistema) hacía que el movimiento se trabara
    private var metrics: DisplayMetrics? = null
    private var navH = -1

    private fun screen() = metrics ?: DisplayMetrics().also { wm.defaultDisplay.getRealMetrics(it); metrics = it }

    override fun onConfigurationChanged(c: android.content.res.Configuration) {  // giro de pantalla: recalcula
        super.onConfigurationChanged(c)
        metrics = null
        navH = -1
    }

    private fun floor(): Float {  // y del piso: encima de la barra de navegación
        if (navH < 0) navH = resources.getIdentifier("navigation_bar_height", "dimen", "android").let { if (it > 0) resources.getDimensionPixelSize(it) else 0 }
        return (screen().heightPixels - size - navH).toFloat()
    }

    private fun setState(s: Int, ms: Long) {
        state = s
        until = System.currentTimeMillis() + ms
        rot = if (s == WALL || s == CLING) (if (side < 0) 90f else -90f) else 0f  // pies contra la pared
        anim = when (s) {
            WALK -> if (dir > 0) "running-right" else "running-left"
            WALL -> "climbing"
            CLING -> "clinging"
            FALL -> "falling"
            DRAG -> "dragged"
            else -> if (anim == "listening" || anim.isNotEmpty() && ms > 0) anim else "idle"
        }
        sp.start(anim)
    }

    /** Menú al tocarla: las acciones del tamagotchi (como el clic en el escritorio); ❗ marca la que sube la barra más baja. */
    private fun showMenu() {
        closeMenu()
        care.tick()
        val w = care.worst()
        val pad = (8 * density).toInt()
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(0xEE222222.toInt())
            setPadding(pad, pad, pad, pad)
            setOnTouchListener { _, e -> if (e.action == MotionEvent.ACTION_OUTSIDE) closeMenu(); false }
        }
        Care.ACTIONS.forEach { a ->
            col.addView(TextView(this).apply {
                text = (if (w >= 0 && a.fx[w] > 0) "❗ " else "") + "${a.icon} ${a.label}"
                setTextColor(0xFFFFFFFF.toInt())
                textSize = 16f
                setPadding(pad * 2, pad, pad * 2, pad)
                setOnClickListener { closeMenu(); care.act(a); anim = a.anim; setState(IDLE, 3000) }
            })
        }
        val menuW = (170 * density).toInt()
        val menuH = (240 * density).toInt()
        val px = x.toInt()  // dentro de apply{} x/y serían los del LayoutParams
        val py = y.toInt()
        val mlp = WindowManager.LayoutParams(WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_WATCH_OUTSIDE_TOUCH, PixelFormat.TRANSLUCENT).apply {
            gravity = Gravity.TOP or Gravity.LEFT
            x = px.coerceIn(0, maxOf(0, screen().widthPixels - menuW))
            y = if (py + size + menuH > screen().heightPixels) maxOf(0, py - menuH) else py + size
        }
        wm.addView(col, mlp)
        menu = col
    }

    private fun closeMenu() {
        menu?.let { wm.removeView(it) }
        menu = null
    }

    /** Mantiene a la mascota fuera del espacio libre (como Pet.free_range en el escritorio). */
    private fun clampFree(px: Float, w: Float): Float = when (freeSide) {
        "right" -> px.coerceAtMost(w * (1 - freeFrac))
        "left" -> px.coerceAtLeast(w * freeFrac)
        else -> px
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
        if (now - careAt > 30_000) {  // cada 30 s baja el tamagotchi y, si algo está bajo, avisa (como el globo del escritorio)
            careAt = now
            care.tick()
            val low = care.worst()
            if (low >= 0 && now - lowAt > 300_000) {
                lowAt = now
                Toast.makeText(this, "${Care.ICONS[low]} Tengo poca ${Care.NAMES[low].lowercase()}… toca para cuidarme", Toast.LENGTH_LONG).show()
            }
        }
        val ls = now < VoiceService.listenUntil  // te está escuchando: se queda quieta con «listening»
        if (ls != listening) {
            listening = ls
            if (state == IDLE || state == WALK) {
                anim = if (ls) "listening" else ""
                setState(IDLE, if (ls) VoiceService.listenUntil - now else 600)
            }
        }
        if (!held) when (state) {  // con el dedo encima se queda quieto: si no, se movía bajo el dedo y el arrastre saltaba
            IDLE -> { y = fl; if (now > until) next() }
            WALK -> {
                x += dir * SPEED_DP * density * dt
                y = fl
                if (freeSide.isNotEmpty() && clampFree(x, w) != x) { x = clampFree(x, w); dir = -dir }  // llegó al límite del espacio libre: da la vuelta
                else if (x <= 0 || x >= w) {
                    x = x.coerceIn(0f, w)
                    side = if (x <= 0) -1 else 1
                    if (Random.nextBoolean()) setState(WALL, 2000L + Random.nextInt(3000))
                    else { dir = -dir; setState(WALK, 2000L + Random.nextInt(4000)) }
                } else if (now > until) next()
            }
            WALL -> {
                x = if (side < 0) 0f else w
                y -= CLIMB_DP * density * dt
                if (y <= 0) { y = 0f; setState(CLING, 1500L + Random.nextInt(2500)) }  // llegó arriba: se agarra quieta
                else if (now > until) setState(if (Random.nextBoolean()) CLING else FALL, 1500L + Random.nextInt(2500))
            }
            CLING -> {
                x = if (side < 0) 0f else w
                if (now > until) { vx = 0f; vy = 0f; setState(FALL, 0) }
            }
            FALL -> {
                vy += GRAVITY_DP * density * dt
                x += vx * dt
                y += vy * dt
                if ((x <= 0 || x >= w) && y < fl) { side = if (x <= 0) -1 else 1; setState(WALL, 2000L + Random.nextInt(3000)) }  // se pega a la pared
                else if (y >= fl) { y = fl; vx = 0f; vy = 0f; anim = ""; setState(IDLE, 600) }
                x = x.coerceIn(0f, w)
            }
        }  // DRAG: lo mueve el dedo (onTouchEvent ya actualiza la ventana)
        v.rotation = rot  // la vista (cuadrada) gira sobre su centro
        if (lp.x != x.toInt() || lp.y != y.toInt()) {
            lp.x = x.toInt()
            lp.y = y.toInt()
            wm.updateViewLayout(v, lp)
        }
        v.invalidate()
        h.postDelayed(::tick, 33)
    }

    override fun onDestroy() {
        h.removeCallbacksAndMessages(null)
        closeMenu()
        view?.let { wm.removeView(it) }
        view = null
        running = false
        super.onDestroy()
    }

    private inner class PetView : View(this@OverlayService) {
        private var offX = 0f
        private var offY = 0f
        private var downX = 0f
        private var downY = 0f
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
            val now = e.eventTime  // hora del evento, no del proceso: velocidad de lanzamiento más estable
            when (e.action) {
                MotionEvent.ACTION_DOWN -> { held = true; offX = rx - x; offY = ry - y; downX = rx; downY = ry; lastX = rx; lastY = ry; lastT = now; mx = 0f; my = 0f; dragging = false }
                MotionEvent.ACTION_MOVE -> {
                    if (!dragging && hypot(rx - downX, ry - downY) > 12 * density) { dragging = true; setState(DRAG, 0) }
                    if (dragging) {
                        val dtm = maxOf(1L, now - lastT) / 1000f
                        mx = 0.5f * mx + 0.5f * (rx - lastX) / dtm  // velocidad del dedo (suavizada) para el lanzamiento
                        my = 0.5f * my + 0.5f * (ry - lastY) / dtm
                        lastX = rx; lastY = ry; lastT = now
                        x = rx - offX
                        y = ry - offY
                        lp.x = x.toInt()  // mueve la ventana ya, no hasta el siguiente tick: si no, el personaje se corta tras el dedo
                        lp.y = y.toInt()
                        wm.updateViewLayout(this, lp)
                    }
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    held = false
                    last = System.currentTimeMillis()  // sin esto el primer tick tras soltar ve un salto de tiempo
                    if (dragging) {
                        val cap = 2500 * density
                        val stale = now - lastT > 100
                        vx = (if (stale) 0f else mx).coerceIn(-cap, cap)
                        vy = (if (stale) 0f else my).coerceIn(-cap, cap)
                        setState(FALL, 0)
                    } else if (e.action == MotionEvent.ACTION_UP) {
                        anim = "waving"
                        setState(IDLE, 2000)
                        showMenu()
                    }
                }
                else -> return false
            }
            return true
        }
    }

    companion object {
        const val STOP = "com.ojitos369.fruquis.STOP"
        const val RELOAD = "com.ojitos369.fruquis.RELOAD"
        const val MOVE = "com.ojitos369.fruquis.MOVE"
        const val FREE = "com.ojitos369.fruquis.FREE"
        const val CHANNEL = "pet"
        @Volatile var running = false
        private const val IDLE = 0
        private const val WALK = 1
        private const val WALL = 2
        private const val FALL = 3
        private const val DRAG = 4
        private const val CLING = 5
        private const val SIZE_DP = 120f
        private const val SPEED_DP = 60f
        private const val CLIMB_DP = 70f
        private const val GRAVITY_DP = 1400f
    }
}
