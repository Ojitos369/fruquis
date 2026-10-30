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
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.graphics.PixelFormat
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.provider.Settings
import android.text.Layout
import android.text.StaticLayout
import android.text.TextPaint
import android.text.TextUtils
import android.util.DisplayMetrics
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import kotlin.math.hypot
import kotlin.random.Random

/** Mascota flotante sobre las demás apps (como los shimejis): camina por el piso, trepa las paredes, se agarra y se lanza con físicas.
 *  Tocarla abre el menú (como el clic en el escritorio) y jalarla la mueve. Ventana TYPE_APPLICATION_OVERLAY (permiso «Mostrar sobre otras apps») mantenida por un servicio en primer plano.
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
    private var flip = 1f  // -1: espejo horizontal (trepar o agarrada con la pared a la derecha)
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
    private var menuClosed = 0L
    private var careAt = 0L
    private var lowAt = 0L
    private var bubble: BubbleView? = null  // globo de diálogo (ventana propia que sigue a la mascota)
    private lateinit var blp: WindowManager.LayoutParams
    private var bubbleUntil = 0L

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
        if (i?.action == SAY && view != null) {  // globo con la respuesta o con lo que está haciendo (thought = nube de pensamiento)
            val t = i.getStringExtra("text") ?: ""
            if (t.isEmpty()) hideBubble() else say(t, i.getLongExtra("ms", 6000), i.getBooleanExtra("thought", false))
            return START_NOT_STICKY
        }
        if (i?.action == RELOAD && view != null) {  // otro personaje, animación editada o nuevo tamaño (Ajustes)
            if (sp.load(MainActivity.activeDir(this))) sp.start(anim)
            resize()
            return START_NOT_STICKY
        }
        if (i?.action == PREVIEW && view != null) {  // «Probar en la mascota» del catálogo o animación pedida en el chat: la reproduce un rato, de pie en el piso
            closeMenu()
            preview(i.getStringExtra("anim") ?: "idle", i.getLongExtra("ms", 3000))
            return START_NOT_STICKY
        }
        try {
            startInForeground()
        } catch (e: Exception) {  // reinicio automático (START_STICKY) que el sistema no deja pasar a primer plano
            stopSelf()
            return START_NOT_STICKY
        }
        if (view == null) {
            if (!Settings.canDrawOverlays(this) || !sp.load(MainActivity.activeDir(this)) || !sp.ok) {
                Toast.makeText(this, "Falta el permiso de superposición o importar un personaje", Toast.LENGTH_LONG).show()
                stopSelf()
                return START_NOT_STICKY
            }
            create()
        }
        return START_STICKY  // si el sistema la cierra por memoria, vuelve sola
    }

    private fun startInForeground() {
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CHANNEL, "Mascota flotante", NotificationManager.IMPORTANCE_LOW))
        val stop = PendingIntent.getService(this, 0, Intent(this, OverlayService::class.java).setAction(STOP), PendingIntent.FLAG_IMMUTABLE)
        val n = Notification.Builder(this, CHANNEL).setSmallIcon(android.R.drawable.ic_menu_gallery).setContentTitle("Fruquis está flotando")
            .setContentText("Toca para quitarla de la pantalla").setContentIntent(stop)
            .setOngoing(true).addAction(android.R.drawable.ic_menu_close_clear_cancel, "Quitar", stop).build()
        if (Build.VERSION.SDK_INT >= 34) startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE) else startForeground(1, n)
    }

    private fun create() {
        running = true
        wm = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        density = resources.displayMetrics.density
        size = petSize()
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

    /** Tamaño en Ajustes (store "scale" del escritorio: 0.3–1.2, 0.6 por defecto). */
    private fun petSize() = (getSharedPreferences("app", MODE_PRIVATE).getFloat("scale", 0.6f) * SIZE_DP * density).toInt()

    private fun resize() {
        val s = petSize()
        if (s == size) return
        y += size - s  // mantiene los pies donde estaban
        size = s
        lp.width = s
        lp.height = s
        view?.let { wm.updateViewLayout(it, lp) }
    }

    private fun preview(name: String, ms: Long = 3000) {
        y = floor()
        anim = name
        setState(IDLE, ms)
    }

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
        // trepar y agarrada se dibujan ya en la pared (de pie, pared a su izquierda): sin girar, solo se voltea si la pared está a la derecha
        val onWall = (s == WALL || s == CLING) && sp.current in WALL_ANIMS
        if (onWall) rot = 0f
        flip = if (onWall && side > 0) -1f else 1f
    }

    /** Menú al tocarla, como Pet.menu del escritorio: acciones del tamagotchi (❗ marca la que sube la barra más baja), «Animación» para
     *  reproducir cualquiera, abrir la app en Chat / Cuidar / Personajes / Ajustes y quitarla de la pantalla. Mientras está abierto la mascota se queda quieta. */
    private fun showMenu(anims: Boolean = false) {
        closeMenu()
        val pad = (8 * density).toInt()
        val col = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        fun item(text: String, dim: Boolean = false, fn: () -> Unit) = col.addView(TextView(this).apply {
            this.text = text
            setTextColor(if (dim) 0xFF8D8DA0.toInt() else 0xFFECECF1.toInt())
            textSize = 16f
            setPadding(pad * 2, (pad * 1.4f).toInt(), pad * 2, (pad * 1.4f).toInt())
            setOnClickListener { fn() }
        })
        if (anims) {
            item("‹  Volver", true) { showMenu() }
            sp.names.sortedBy { Sprite.label(it) }.forEach { n -> item(Sprite.label(n)) { closeMenu(); preview(n) } }
        } else {
            care.tick()
            val w = care.worst()
            Care.ACTIONS.forEach { a ->
                item((if (w >= 0 && a.fx[w] > 0) "❗ " else "") + "${a.icon}  ${a.label}") { closeMenu(); care.act(a); anim = a.anim; setState(IDLE, 3000) }
            }
            item("🎬  Animación  ›") { showMenu(true) }
            listOf("chat" to "💬  Chat", "care" to "🍙  Cuidar", "chars" to "🧸  Personajes", "settings" to "⚙  Ajustes").forEach { (tab, label) ->
                item(label) {
                    closeMenu()
                    startActivity(Intent(this, MainActivity::class.java).putExtra("tab", tab).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP))
                }
            }
            item("✕  Quitar de la pantalla", true) { closeMenu(); stopSelf() }
        }
        val scr = screen()
        col.measure(View.MeasureSpec.UNSPECIFIED, View.MeasureSpec.UNSPECIFIED)
        val menuW = col.measuredWidth + 2 * pad
        val menuH = minOf(col.measuredHeight + 2 * pad, (scr.heightPixels * 0.6f).toInt())  // la lista de animaciones es larga: se desplaza
        val root = ScrollView(this).apply {
            background = android.graphics.drawable.GradientDrawable().apply { setColor(0xF01C1C24.toInt()); cornerRadius = 16 * density }
            setPadding(pad, pad, pad, pad)
            addView(col)
            setOnTouchListener { _, e -> if (e.action == MotionEvent.ACTION_OUTSIDE) closeMenu(); false }
        }
        val px = x.toInt()  // dentro de apply{} x/y serían los del LayoutParams
        val py = y.toInt()
        val mlp = WindowManager.LayoutParams(menuW, menuH, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_WATCH_OUTSIDE_TOUCH, PixelFormat.TRANSLUCENT).apply {
            gravity = Gravity.TOP or Gravity.LEFT
            x = (px + size / 2 - menuW / 2).coerceIn(0, maxOf(0, scr.widthPixels - menuW))
            y = (if (py - menuH > 0) py - menuH else py + size).coerceIn(0, maxOf(0, scr.heightPixels - menuH))  // arriba de ella; si no cabe, abajo
        }
        wm.addView(root, mlp)
        menu = root
    }

    private fun closeMenu() {
        menu?.let { wm.removeView(it); menuClosed = System.currentTimeMillis() }
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
                say("${Care.ICONS[low]} Tengo poca ${Care.NAMES[low].lowercase()}… toca para cuidarme", 8000, false)
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
        if (!held && menu == null) when (state) {  // con el dedo encima o el menú abierto se queda quieta: si no, se movía bajo el dedo y el arrastre saltaba
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
                // se pega a la pared solo si va hacia ella: al soltarse de la pared (vx = 0) volvía a agarrarse y se quedaba trabada en la esquina
                if ((x <= 0 && vx < 0 || x >= w && vx > 0) && y < fl) { side = if (x <= 0) -1 else 1; setState(WALL, 2000L + Random.nextInt(3000)) }
                else if (y >= fl) { y = fl; vx = 0f; vy = 0f; anim = ""; setState(IDLE, 600) }
                x = x.coerceIn(0f, w)
            }
        }  // DRAG: lo mueve el dedo (onTouchEvent ya actualiza la ventana)
        v.rotation = rot  // la vista (cuadrada) gira sobre su centro
        v.scaleX = flip
        if (lp.x != x.toInt() || lp.y != y.toInt()) {
            lp.x = x.toInt()
            lp.y = y.toInt()
            wm.updateViewLayout(v, lp)
        }
        v.invalidate()
        placeBubble()
        h.postDelayed(::tick, 33)
    }

    /** Estado para depurar por adb: `adb shell dumpsys activity service com.ojitos369.fruquis/.OverlayService`. */
    override fun dump(fd: java.io.FileDescriptor?, w: java.io.PrintWriter, args: Array<out String>?) {
        w.println("state=$state anim=$anim sprite=${sp.current} held=$held menu=${menu != null} x=$x y=$y rot=$rot until=${until - System.currentTimeMillis()} " +
            "size=$size view=${view?.let { "${it.width}x${it.height} vis=${it.visibility} alpha=${it.alpha} rot=${it.rotation} attached=${it.isAttachedToWindow}" }}")
    }

    private fun say(text: String, ms: Long, thought: Boolean) {
        val b = bubble ?: BubbleView().also {
            blp = WindowManager.LayoutParams(1, 1, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS or
                    WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN, PixelFormat.TRANSLUCENT).apply { gravity = Gravity.TOP or Gravity.LEFT }
            wm.addView(it, blp)
            bubble = it
        }
        b.set(text, thought)
        bubbleUntil = System.currentTimeMillis() + ms
        placeBubble(true)
    }

    private fun hideBubble() {
        bubble?.let { wm.removeView(it) }
        bubble = null
    }

    /** Encima de la mascota con la flechita hacia ella; si no cabe, debajo (como Bubble.say del escritorio). */
    private fun placeBubble(force: Boolean = false) {
        val b = bubble ?: return
        if (System.currentTimeMillis() > bubbleUntil) return hideBubble()
        val scr = screen()
        val cx = x + size / 2
        val bx = (cx - b.bw / 2).toInt().coerceIn(0, maxOf(0, scr.widthPixels - b.bw))
        var by = (y - b.bh).toInt()
        val above = by >= 0
        if (!above) by = (y + size).toInt()
        val tx = (cx - bx).coerceIn(18 * density, b.bw - 18 * density)
        if (!force && blp.x == bx && blp.y == by && b.above == above && b.tailX == tx) return
        b.above = above
        b.tailX = tx
        blp.x = bx
        blp.y = by
        blp.width = b.bw
        blp.height = b.bh
        wm.updateViewLayout(b, blp)
        b.invalidate()
    }

    override fun onDestroy() {
        h.removeCallbacksAndMessages(null)
        hideBubble()
        closeMenu()
        view?.let { wm.removeView(it) }
        view = null
        running = false
        super.onDestroy()
    }

    /** Globo como Bubble de fruquis/app.py: relleno crema, borde morado, flechita a la mascota; `thought` = nube con dos burbujitas. Tocarlo lo cierra. */
    private inner class BubbleView : View(this@OverlayService) {
        private val d = density
        private val text = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xFF2B2140.toInt(); textSize = 14 * resources.displayMetrics.scaledDensity }
        private val fill = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xFFFFFBE9.toInt() }
        private val edge = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xFF8A7BD6.toInt(); style = Paint.Style.STROKE; strokeWidth = 2 * d; strokeJoin = Paint.Join.ROUND }
        private val tail = 11 * d
        private val padH = 12 * d
        private val padV = 8 * d
        private var lay: StaticLayout? = null
        private var thought = false
        var above = true
        var tailX = 0f
        var bw = 1
        var bh = 1

        fun set(raw: String, th: Boolean) {
            thought = th
            val t = raw.replace(Regex("\\[([^\\]]+)]\\([^)]+\\)"), "$1").replace(Regex("\\*\\*|__|`|^#+ ", RegexOption.MULTILINE), "")  // markdown simple → texto
            val maxW = (minOf(280 * d, screen().widthPixels * 0.8f) - 2 * padH).toInt()
            val w = minOf(maxW, Math.ceil(Layout.getDesiredWidth(t, text).toDouble()).toInt()).coerceAtLeast(1)
            lay = StaticLayout.Builder.obtain(t, 0, t.length, text, w).setMaxLines(14).setEllipsize(TextUtils.TruncateAt.END).build()
            bw = (w + 2 * padH).toInt()
            bh = (lay!!.height + 2 * padV + tail).toInt()
        }

        override fun onDraw(c: Canvas) {
            val l = lay ?: return
            val top = if (above) 0f else tail
            val body = RectF(1.5f * d, top + 1.5f * d, bw - 1.5f * d, top + bh - tail - 1.5f * d)
            val path = Path()
            if (thought) {
                val r = minOf(body.height(), 40 * d) / 2
                path.addRoundRect(body, r, r, Path.Direction.CW)
                val sgn = if (above) 1 else -1
                val y0 = if (above) body.bottom else body.top
                path.addCircle(tailX, y0 + sgn * 4 * d, 4 * d, Path.Direction.CW)
                path.addCircle(tailX, y0 + sgn * 9.5f * d, 2.5f * d, Path.Direction.CW)
            } else {
                path.addRoundRect(body, 12 * d, 12 * d, Path.Direction.CW)
                val tri = Path().apply {
                    if (above) { moveTo(tailX - 9 * d, body.bottom - 1); lineTo(tailX + 9 * d, body.bottom - 1); lineTo(tailX, body.bottom + tail - 2 * d) }
                    else { moveTo(tailX - 9 * d, body.top + 1); lineTo(tailX + 9 * d, body.top + 1); lineTo(tailX, body.top - tail + 2 * d) }
                    close()
                }
                path.op(tri, Path.Op.UNION)  // un solo contorno: no se marca la base de la flecha
            }
            c.drawPath(path, fill)
            c.drawPath(path, edge)
            c.translate(padH, top + padV)
            l.draw(c)
        }

        override fun onTouchEvent(e: MotionEvent): Boolean {
            if (e.action == MotionEvent.ACTION_UP) hideBubble()
            return true
        }
    }

    private inner class PetView : View(this@OverlayService) {
        // aquí `x`/`y` a secas son la traslación de la propia View: usarlos movía el dibujo fuera de su ventana y al jalarla se cortaba o
        // desaparecía. La posición de la mascota es la del servicio.
        private val pet = this@OverlayService
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
        private var hadMenu = false
        private val slop = ViewConfiguration.get(this@OverlayService).scaledTouchSlop.toFloat()

        override fun onDraw(c: Canvas) {
            sp.draw(c, width, height)
        }

        override fun onTouchEvent(e: MotionEvent): Boolean {
            val rx = e.rawX
            val ry = e.rawY
            val now = e.eventTime  // hora del evento, no del proceso: velocidad de lanzamiento más estable
            when (e.action) {
                MotionEvent.ACTION_DOWN -> {
                    held = true; offX = rx - pet.x; offY = ry - pet.y; downX = rx; downY = ry; lastX = rx; lastY = ry; lastT = now; mx = 0f; my = 0f; dragging = false
                    hadMenu = menu != null || System.currentTimeMillis() - menuClosed < 400  // el toque fuera del menú ya lo cerró: este toque solo lo cierra
                    closeMenu()
                }
                MotionEvent.ACTION_MOVE -> {
                    // jalar = mover; menos que el umbral del sistema cuenta como toque (antes 12 dp fijos: un dedo tembloroso la arrastraba sin querer)
                    if (!dragging && hypot(rx - downX, ry - downY) > slop * 1.5f) { dragging = true; rot = 0f; flip = 1f; this.rotation = 0f; this.scaleX = 1f; setState(DRAG, 0) }
                    if (dragging) {
                        val dtm = maxOf(1L, now - lastT) / 1000f
                        mx = 0.5f * mx + 0.5f * (rx - lastX) / dtm  // velocidad del dedo (suavizada) para el lanzamiento
                        my = 0.5f * my + 0.5f * (ry - lastY) / dtm
                        lastX = rx; lastY = ry; lastT = now
                        pet.x = rx - offX
                        pet.y = ry - offY
                        lp.x = pet.x.toInt()  // mueve la ventana ya, no hasta el siguiente tick: si no, el personaje se corta tras el dedo
                        lp.y = pet.y.toInt()
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
                    } else if (e.action == MotionEvent.ACTION_UP && !hadMenu) {  // tocar = abrir el menú (otra vez = cerrarlo)
                        if (state == IDLE || state == WALK) { anim = "waving"; setState(IDLE, 2000) }
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
        const val PREVIEW = "com.ojitos369.fruquis.PREVIEW"
        const val SAY = "com.ojitos369.fruquis.SAY"
        const val CHANNEL = "pet"
        @Volatile var running = false

        /** Globo junto a la mascota flotante (texto vacío = quitarlo). Devuelve false si no está flotando (entonces usa un Toast). */
        fun bubble(c: Context, text: String, ms: Long = maxOf(6000L, text.length * 70L), thought: Boolean = false): Boolean {
            if (!running) return false
            c.startService(Intent(c, OverlayService::class.java).setAction(SAY).putExtra("text", text).putExtra("ms", ms).putExtra("thought", thought))
            return true
        }
        private const val IDLE = 0
        private const val WALK = 1
        private const val WALL = 2
        private const val FALL = 3
        private const val DRAG = 4
        private const val CLING = 5
        private const val SIZE_DP = 200f  // al 100 %; 0.6 (predeterminado) = 120 dp
        private const val SPEED_DP = 60f
        private const val CLIMB_DP = 70f
        private val WALL_ANIMS = setOf("climbing", "clinging")  // como WALL_ANIMS de fruquis/app.py
        private const val GRAVITY_DP = 1400f
    }
}
