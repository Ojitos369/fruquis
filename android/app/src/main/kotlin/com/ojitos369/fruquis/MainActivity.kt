package com.ojitos369.fruquis

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.speech.RecognizerIntent
import android.speech.tts.TextToSpeech
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items as gridItems
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.TextButton
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameMillis
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.InputStream
import java.util.zip.ZipEntry
import java.util.zip.ZipInputStream
import java.util.zip.ZipOutputStream

/** Animación a reproducir; cada instancia es distinta, así que relanza la animación aunque sea la misma. */
private class Play(val anim: String, val ms: Long)

// Paleta de fruquis/theme.py: oscuro, minimalista, un solo acento
private val BG = Color(0xFF16161C)
private val PANEL = Color(0xFF1C1C24)
private val RAISED = Color(0xFF262632)
private val LINE = Color(0xFF2D2D3A)
private val TEXT = Color(0xFFECECF1)
private val DIM = Color(0xFF8D8DA0)
private val ACCENT = Color(0xFF8A6AE0)
private val DANGER = Color(0xFFF07178)
private val SELECTED = Color(0xFF2E2A46)

/** Pestañas como fruquis/shell.py ROOTS. */
private val TABS = listOf("chat" to "💬" to "Chat", "care" to "🍙" to "Cuidar", "chars" to "🧸" to "Personajes", "settings" to "⚙" to "Ajustes")

/** Versión Android de Fruquis: la mascota animada con las mismas hojas de sprites (character.json) y el mismo tamagotchi que el escritorio.
 *  Mantener en paridad con fruquis/care.py (Care.kt) y con el formato de fruquis/sprites.py (Sprite.kt). La mascota flotante es OverlayService. */
class MainActivity : ComponentActivity() {
    private val care by lazy { Care(getSharedPreferences("care", MODE_PRIVATE)) }
    private val sprite = Sprite()
    private var charVersion by mutableStateOf(0)  // sube al importar o cambiar de personaje
    private var floating by mutableStateOf(false)
    private var play by mutableStateOf(Play("idle", 0))
    private val chat = mutableStateListOf<Pair<Boolean, String>>()  // (es del usuario, texto)
    private var tab by mutableStateOf("care")  // la mascota flotante abre la app en una pestaña (extra "tab")
    private var tts: TextToSpeech? = null  // respuestas del chat en voz alta (Speech en VoiceService.kt)

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        enableEdgeToEdge()
        tts = TextToSpeech(this) {}  // arranca ya: el motor tarda en estar listo
        setContent {
            MaterialTheme(colorScheme = darkColorScheme(primary = ACCENT, onPrimary = Color.White, background = BG, surface = BG,
                onBackground = TEXT, onSurface = TEXT, surfaceVariant = RAISED, onSurfaceVariant = DIM, outline = LINE,
                secondaryContainer = SELECTED, error = DANGER)) { Home() }
        }
        intent?.getStringExtra("tab")?.let { tab = it }
        if (Link.conf(this).code.isNotEmpty() && !Link.running) startLink()  // vinculado: sigue recibiendo órdenes y archivos
    }

    /** Arranca (o reinicia con los ajustes nuevos) el servicio del vínculo con otro equipo. */
    private fun startLink() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission("android.permission.POST_NOTIFICATIONS") != PackageManager.PERMISSION_GRANTED)
            requestPermissions(arrayOf("android.permission.POST_NOTIFICATIONS"), 2)  // para el aviso fijo y para «Permitir / Rechazar» una orden
        startForegroundService(Intent(this, LinkService::class.java))
    }

    override fun onDestroy() {
        tts?.shutdown()
        super.onDestroy()
    }

    override fun onNewIntent(i: Intent) {
        super.onNewIntent(i)
        i.getStringExtra("tab")?.let { tab = it }
    }

    override fun onResume() {
        super.onResume()
        care.load()
        floating = OverlayService.running
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_LONG).show()

    private fun dir() = activeDir(this)

    private fun charName() = listChars()[dir().name] ?: "Fruquis"

    /** Avisa a la mascota flotante que recargue personaje, animaciones o tamaño. */
    private fun reloadFloat() {
        if (OverlayService.running) startService(Intent(this, OverlayService::class.java).setAction(OverlayService.RELOAD))
    }

    /** Personajes instalados: id → nombre (de character.json), como sprites.list_all. */
    private fun listChars(): Map<String, String> = (charsDir(this).listFiles() ?: emptyArray()).sortedBy { it.name }
        .filter { File(it, "character.json").exists() }
        .associate { it.name to (runCatching { JSONObject(File(it, "character.json").readText()).optString("name", it.name) }.getOrNull() ?: it.name) }

    companion object {
        fun charsDir(c: Context) = File(c.filesDir, "characters").apply {
            mkdirs()
            val old = File(c.filesDir, "character")  // versión anterior: un solo personaje en files/character
            if (old.exists() && old.renameTo(File(this, "personaje"))) prefs(c).edit().putString("active", "personaje").apply()
        }
        private fun prefs(c: Context) = c.getSharedPreferences("app", Context.MODE_PRIVATE)
        /** Carpeta del personaje activo (store "active" en escritorio); si no existe, la primera que haya. */
        fun activeDir(c: Context): File {
            val all = charsDir(c).listFiles { f -> File(f, "character.json").exists() }?.sortedBy { it.name } ?: emptyList()
            return all.firstOrNull { it.name == prefs(c).getString("active", "") } ?: all.firstOrNull() ?: File(charsDir(c), "_")
        }
        fun setActive(c: Context, id: String) = prefs(c).edit().putString("active", id).apply()
        fun slug(t: String) = t.lowercase().replace(" ", "-").replace("_", "-").replace(Regex("[^a-z0-9-]"), "").trim('-').ifEmpty { "personaje" }
    }

    @Composable
    private fun Home() {
        val tick = remember { mutableLongStateOf(0) }

        LaunchedEffect(charVersion) { sprite.load(dir()); sprite.start(play.anim) }
        LaunchedEffect(play) {
            sprite.start(play.anim)
            if (play.ms > 0) { delay(play.ms); play = Play("idle", 0) }
        }
        LaunchedEffect(Unit) { while (true) { delay(60_000); care.tick() } }
        LaunchedEffect(Unit) {  // el asistente de voz espera la orden: la mascota de la app también escucha
            while (true) {
                delay(300)
                val left = VoiceService.listenUntil - System.currentTimeMillis()
                if (left > 0 && play.anim != "listening") play = Play("listening", left)
            }
        }
        LaunchedEffect(Unit) { while (true) withFrameMillis { tick.longValue = it } }  // redibuja la mascota en cada cuadro

        Scaffold(containerColor = BG, bottomBar = {
            NavigationBar(containerColor = PANEL, tonalElevation = 0.dp) {
                TABS.forEach { (k, label) ->
                    NavigationBarItem(tab == k.first, { tab = k.first }, icon = { Text(k.second, fontSize = 20.sp) }, label = { Text(label) }, alwaysShowLabel = false,
                        colors = NavigationBarItemDefaults.colors(indicatorColor = SELECTED, selectedTextColor = TEXT, unselectedTextColor = DIM))
                }
            }
        }) { pad ->
            Column(Modifier.padding(pad).consumeWindowInsets(pad).imePadding().fillMaxSize().padding(horizontal = 16.dp, vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                when (tab) {
                    "chat" -> ChatTab(tick)
                    "care" -> CareTab(tick)
                    "chars" -> CharsTab(tick)
                    "settings" -> SettingsTab()
                }
            }
        }
    }

    @Composable
    private fun Pet(tick: androidx.compose.runtime.MutableLongState, m: Modifier, sp: Sprite = sprite) {
        Canvas(m) {
            tick.longValue  // lee el estado para que cada cuadro redibuje
            drawIntoCanvas { sp.draw(it.nativeCanvas, size.width.toInt(), size.height.toInt()) }
        }
    }

    @Composable
    private fun H1(text: String) = Text(text, fontSize = 22.sp, fontWeight = FontWeight.SemiBold)

    @Composable
    private fun Section(text: String) = Text(text.uppercase(), color = DIM, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.sp)

    @Composable
    private fun Card(m: Modifier = Modifier, content: @Composable () -> Unit) =
        Box(m.clip(RoundedCornerShape(16.dp)).background(PANEL).padding(16.dp)) { content() }

    /** Botón de solo icono: tocar = acción; mantener pulsado = dice qué hace (como el tooltip del escritorio).
     *  kind: "" discreto, "r" con fondo, "p" principal, "d" peligroso. `wide`: ocupa el ancho que le dé `m` (en vez de ser cuadrado). */
    @OptIn(ExperimentalFoundationApi::class)
    @Composable
    private fun IconBtn(glyph: String, tip: String, m: Modifier = Modifier, kind: String = "", size: Dp = 44.dp, on: Boolean = false, wide: Boolean = false, onClick: () -> Unit) {
        val bg = when { on -> SELECTED; kind == "p" -> ACCENT; kind == "r" -> RAISED; else -> Color.Transparent }
        Box((if (wide) m.height(size) else m.size(size)).clip(RoundedCornerShape(12.dp)).background(bg)
            .combinedClickable(onClick = onClick, onLongClick = { toast(tip) }).semantics { contentDescription = tip }, contentAlignment = Alignment.Center) {
            Text(glyph, color = when (kind) { "d" -> DANGER; "p" -> Color.White; else -> TEXT }, fontSize = (size.value * 0.42f).sp)
        }
    }

    /** CareView: barras finas (rojas bajo 25) y acciones como iconos (mantener pulsado dice cuál es). */
    @Composable
    private fun CareTab(tick: androidx.compose.runtime.MutableLongState) {
        Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.weight(1f)) { H1(remember(charVersion) { charName() }) }
                IconBtn(if (floating) "✕" else "👻", if (floating) "Quitar mascota flotante" else "Mascota flotante", kind = if (floating) "r" else "p") { toggleFloat() }
            }
            Pet(tick, Modifier.weight(1f).fillMaxWidth())
            Card(Modifier.fillMaxWidth()) {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Care.NAMES.forEachIndexed { i, _ ->
                        val v = care.stats[i]
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(Care.ICONS[i], Modifier.width(32.dp))
                            LinearProgressIndicator(progress = { (v / 100).toFloat() }, Modifier.weight(1f).height(8.dp).clip(RoundedCornerShape(4.dp)),
                                color = if (v < 25) DANGER else ACCENT, trackColor = RAISED, strokeCap = StrokeCap.Round, gapSize = 0.dp, drawStopIndicator = {})
                        }
                    }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Care.ACTIONS.forEach { a -> IconBtn(a.icon, a.label, Modifier.weight(1f), kind = "r", size = 52.dp, wide = true) { care.act(a); play = Play(a.anim, 3000) } }
            }
        }
    }

    /** ChatView: conversación con el personaje activo por la API configurada. */
    @Composable
    private fun androidx.compose.foundation.layout.ColumnScope.ChatTab(tick: androidx.compose.runtime.MutableLongState) {
        var text by remember { mutableStateOf("") }
        var busy by remember { mutableStateOf(false) }
        var job by remember { mutableStateOf<Job?>(null) }
        var imgs by remember { mutableStateOf<List<Uri>>(emptyList()) }  // imágenes de referencia para el próximo mensaje
        var sent by remember { mutableStateOf<List<Uri>>(emptyList()) }  // las del mensaje en curso (vuelven al cancelar)
        val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { imgs = it }
        val scope = rememberCoroutineScope()
        val list = rememberLazyListState()

        fun send(raw: String) {
            val msg = raw.trim()
            if (msg.isEmpty() || busy) return
            if (VoiceService.isNewChat(msg)) { chat.clear(); text = ""; imgs = emptyList(); return }  // «nuevo chat»
            if (imgs.isEmpty()) Link.parse(this@MainActivity, msg)?.let { (to, order) ->  // «dile a la PC que…»: la ejecuta el otro equipo
                text = ""
                chat.add(true to msg)
                scope.launch {
                    chat.add(false to withContext(Dispatchers.IO) {
                        try { "📲 Se lo mandé a ${to.ifEmpty { "tu otro equipo" }} (por ${Link.send(this@MainActivity, "task", order, to)}). Te aviso cuando responda." }
                        catch (e: Exception) { "📲 No pude mandarlo: ${e.message}" }
                    })
                }
                return
            }
            text = ""
            busy = true
            sent = imgs
            imgs = emptyList()
            val name = charName()
            val ctx = chat.takeLast(10).joinToString("\n") { (m, t) -> (if (m) "Tú: " else "$name: ") + t }
            chat.add(true to msg + if (sent.isEmpty()) "" else "\n📎 ${sent.size} imagen(es)")
            play = Play("talking", 120_000)
            OverlayService.bubble(this@MainActivity, "💭 Pensando…", 300_000, true)  // globo de pensamiento, como el escritorio
            job = scope.launch {
                val raw = withContext(Dispatchers.IO) {
                    try {
                        val q = if (ctx.isEmpty()) msg else "$ctx\nTú: $msg"
                        val phone = sent.isEmpty() && PhoneService.on(this@MainActivity)
                        val persona = Persona.system(this@MainActivity, anims = !phone)  // como chat.persona_prompt (con PhoneService la IA responde JSON)
                        if (phone) PhoneService.run(this@MainActivity, q, persona, { !isActive }) { a ->  // maneja el teléfono
                            OverlayService.bubble(this@MainActivity, PhoneService.STEP_TEXT[a] ?: "📱 …", 300_000, true)
                        }
                        else Ai(getSharedPreferences("ai", MODE_PRIVATE)).chat(q, persona, sent.map { jpeg(it) })
                    } catch (e: Exception) {
                        "No pude responder (${e.message})"
                    }
                }
                val (reply, anim) = Persona.split(raw, Persona.acts(this@MainActivity))  // [[anim:…]]: la animación que pidió (bañarse, comer…)
                VoiceLog.add(this@MainActivity, "respuesta", "pedido" to msg, "origen" to "chat", "respuesta" to reply, "animacion" to (anim ?: ""))
                chat.add(false to reply)
                if (!reply.startsWith("No pude responder")) Speech.say(this@MainActivity, tts, reply)
                // chat cerrado (otra app al frente u otra pestaña): la respuesta sale en un globo junto a la mascota, como en el escritorio
                if (!lifecycle.currentState.isAtLeast(androidx.lifecycle.Lifecycle.State.RESUMED) || tab != "chat")
                    OverlayService.bubble(this@MainActivity, reply).let { shown -> if (!shown) toast(reply) }
                else OverlayService.bubble(this@MainActivity, "")  // quita el globo de pensamiento
                busy = false
                if (anim != null) Persona.act(this@MainActivity, anim, care)
                play = if (anim != null) Play(anim, 5000) else Play("talking", 2000)
            }
        }
        // botón del micrófono: dicta una orden sin decir el nombre (cuadro de voz del sistema) y la envía
        val mic = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
            r.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()?.let { send(it) }
        }
        LaunchedEffect(chat.size) { if (chat.isNotEmpty()) list.animateScrollToItem(chat.size - 1) }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Pet(tick, Modifier.size(84.dp))  // pequeña: en el teléfono la conversación necesita la pantalla
            Text(remember(charVersion) { charName() }, Modifier.weight(1f).padding(start = 8.dp), fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
            IconBtn("＋", "Nuevo chat", kind = "r") { if (!busy) { chat.clear(); text = ""; imgs = emptyList() } }
        }
        LazyColumn(Modifier.weight(1f).fillMaxWidth(), list, verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (chat.isEmpty()) item { Text("Dile algo a ${charName()} 👋", color = DIM) }
            items(chat) { (mine, t) ->
                Box(Modifier.fillMaxWidth(), contentAlignment = if (mine) Alignment.CenterEnd else Alignment.CenterStart) {
                    SelectionContainer {  // mantener pulsado un mensaje lo selecciona para copiarlo (uno por mensaje: alrededor de la lista tapaba la entrada)
                        Text(t, Modifier.clip(RoundedCornerShape(14.dp)).background(if (mine) SELECTED else PANEL).padding(horizontal = 12.dp, vertical = 8.dp))
                    }
                }
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            // clic = adjuntar imágenes; si ya hay, las quita
            IconBtn(if (imgs.isEmpty()) "📎" else "✓", if (imgs.isEmpty()) "Adjuntar imágenes" else "${imgs.size} imagen(es): toca para quitarlas", kind = "r") {
                if (imgs.isEmpty()) picker.launch(arrayOf("image/*")) else imgs = emptyList()
            }
            IconBtn("🎙", "Dictar una orden", kind = "r") {
                try {
                    mic.launch(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                        .putExtra(RecognizerIntent.EXTRA_LANGUAGE, "es-MX"))
                } catch (e: Exception) {
                    toast("Este teléfono no tiene reconocimiento de voz")
                }
            }
            OutlinedTextField(text, { text = it }, Modifier.weight(1f), placeholder = { Text(if (busy) "Pensando…" else "Escribe…") },
                shape = RoundedCornerShape(12.dp), colors = fieldColors(), maxLines = 4)
            Button({
                if (busy) {  // cancelar: el mensaje y sus imágenes vuelven al cuadro para corregirlos (la petición HTTP termina sola en segundo plano y se descarta)
                    job?.cancel()
                    OverlayService.bubble(this@MainActivity, "")
                    text = chat.removeAt(chat.lastIndex).second.substringBefore("\n📎")  // no removeLast(): falla en Android < 15
                    imgs = sent
                    busy = false
                    play = Play("talking", 500)
                    return@Button
                }
                send(text)
            }, Modifier.size(52.dp), shape = RoundedCornerShape(12.dp), contentPadding = PaddingValues(0.dp)) { Text(if (busy) "✕" else "➤", fontSize = 18.sp) }
        }
    }

    /** CharactersView: catálogo de personajes en cards; tocar el personaje lo activa y bajo su nombre van sus acciones como iconos
     *  (animaciones, editar, exportar, eliminar). Importar no quita a los demás. */
    @Composable
    private fun androidx.compose.foundation.layout.ColumnScope.CharsTab(tick: androidx.compose.runtime.MutableLongState) {
        val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
            if (uri != null) try {
                val id = contentResolver.openInputStream(uri)!!.use { importZip(it) }
                if (listChars().size == 1) useChar(id) else { charVersion++; toast("Importado: ${listChars()[id]}") }
            } catch (e: Exception) {
                toast("No se pudo importar: ${e.message}")
            }
        }
        var exporting by remember { mutableStateOf("") }
        val saver = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/zip")) { uri ->
            if (uri != null) try {
                contentResolver.openOutputStream(uri)!!.use { exportZip(exporting, it) }
                toast("Exportado: $exporting.zip")
            } catch (e: Exception) {
                toast("No se pudo exportar: ${e.message}")
            }
        }
        val chars = remember(charVersion) { listChars() }
        val active = remember(charVersion) { dir().name }
        var editing by remember { mutableStateOf<String?>(null) }
        var deleting by remember { mutableStateOf<String?>(null) }
        var creating by remember { mutableStateOf(false) }
        var catalog by remember { mutableStateOf<String?>(null) }
        catalog?.let { id ->
            BackHandler { catalog = null }
            return CatalogScreen(id, tick) { catalog = null }
        }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            Box(Modifier.weight(1f)) { H1("Personajes") }
            IconBtn("⇪", "Importar (.zip)") { picker.launch(arrayOf("*/*")) }
            IconBtn("＋", "Nuevo personaje", kind = "p") { creating = true }
        }
        LazyVerticalGrid(GridCells.Adaptive(150.dp), Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(12.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            gridItems(chars.toList()) { (id, name) ->
                val on = id == active
                val sp = remember(id, charVersion) { Sprite().also { it.load(File(charsDir(this@MainActivity), id)); it.start("idle") } }
                Column(Modifier.clip(RoundedCornerShape(16.dp)).background(PANEL).border(1.dp, if (on) ACCENT else LINE, RoundedCornerShape(16.dp)).padding(10.dp),
                    horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Pet(tick, Modifier.size(96.dp).clickable(enabled = !on) { useChar(id) }, sp)
                    Text(name, fontWeight = FontWeight.SemiBold, maxLines = 1)
                    Row {
                        IconBtn("🎬", "Animaciones", size = 32.dp) { catalog = id }
                        IconBtn("✎", "Editar", size = 32.dp) { editing = id }
                        IconBtn("⇪", "Exportar (.zip)", size = 32.dp) { exporting = id; saver.launch("$id.zip") }
                        IconBtn("🗑", "Eliminar", kind = "d", size = 32.dp) { deleting = id }
                    }
                }
            }
        }
        if (creating) NewCharDialog { creating = false }
        editing?.let { EditCharDialog(it) { editing = null } }
        deleting?.let { id ->
            AlertDialog(onDismissRequest = { deleting = null }, containerColor = PANEL,
                title = { Text("¿Eliminar a ${chars[id] ?: id}?") },
                confirmButton = { IconBtn("🗑", "Eliminar", kind = "d") { deleteChar(id); deleting = null } },
                dismissButton = { IconBtn("✕", "Cancelar") { deleting = null } })
        }
    }

    /** AnimsView + CatalogView: cuadrícula de cards con la miniatura en movimiento de cada animación (las que tiene y las que le faltan).
     *  Tocar una abre su detalle (vista previa, fps y modo al vuelo como sprites.set_meta, probar en la mascota flotante, eliminar);
     *  mantener pulsada una, o el icono de selección, marca varias (todo / nada / invertir) para eliminarlas. Generar varias es solo de escritorio. */
    @OptIn(ExperimentalFoundationApi::class)
    @Composable
    private fun androidx.compose.foundation.layout.ColumnScope.CatalogScreen(id: String, tick: androidx.compose.runtime.MutableLongState, onBack: () -> Unit) {
        val f = File(File(charsDir(this@MainActivity), id), "character.json")
        var ver by remember { mutableStateOf(0) }
        val j = remember(id, ver) { runCatching { JSONObject(f.readText()) }.getOrDefault(JSONObject()) }
        val anims = j.optJSONObject("anims") ?: JSONObject()
        val names = remember(id, ver) { anims.keys().asSequence().sortedBy { Sprite.label(it) }.toList() + Sprite.WANTED.keys.filter { !anims.has(it) } }
        var sel by remember(id) { mutableStateOf(names.firstOrNull() ?: "") }
        var arm by remember { mutableStateOf(false) }
        var detail by remember(id) { mutableStateOf<String?>(null) }
        var selecting by remember(id) { mutableStateOf(false) }
        var picked by remember(id) { mutableStateOf(setOf<String>()) }
        var armDel by remember { mutableStateOf(false) }
        LaunchedEffect(picked) { armDel = false }
        val a = anims.optJSONObject(sel)
        val prev = remember { Sprite() }
        LaunchedEffect(id, ver, sel) { prev.load(f.parentFile!!); if (a != null) prev.start(sel); arm = false }

        fun save(fps: Int, mode: String) {
            a!!.put("fps", fps.coerceIn(1, 30)).put("loop", mode != "once").put("pingpong", mode == "pingpong")
            f.writeText(j.toString(1))
            ver++
            charVersion++
            reloadFloat()
        }

        if (detail == null) {
            BackHandler(enabled = selecting) { selecting = false; picked = emptySet() }
            Row(verticalAlignment = Alignment.CenterVertically) {
                IconBtn("‹", "Atrás") { onBack() }
                Box(Modifier.weight(1f)) { if (selecting) Text("${picked.size}", color = DIM, fontSize = 16.sp) else H1(j.optString("name", id)) }
                if (selecting) {
                    IconBtn("☑", "Seleccionar todo", size = 40.dp) { picked = names.toSet() }
                    IconBtn("☐", "Deseleccionar todo", size = 40.dp) { picked = emptySet() }
                    IconBtn("⇄", "Invertir selección", size = 40.dp) { picked = names.toSet() - picked }
                    if (picked.any { anims.has(it) }) IconBtn(if (armDel) "✓" else "🗑", if (armDel) "¿Seguro? Toca otra vez" else "Eliminar seleccionadas", kind = "d", size = 40.dp) {
                        if (!armDel) { armDel = true; return@IconBtn }  // confirmación en dos toques, como el escritorio
                        val gone = picked.filter { anims.has(it) }
                        gone.forEach { anims.remove(it) }
                        f.writeText(j.toString(1))
                        toast("${gone.size} eliminada(s)")
                        picked = emptySet()
                        ver++
                        charVersion++
                        reloadFloat()
                    }
                }
                IconBtn(if (selecting) "✕" else "☑", if (selecting) "Salir de la selección" else "Seleccionar", size = 40.dp) { selecting = !selecting; if (!selecting) picked = emptySet() }
            }
            LazyVerticalGrid(GridCells.Adaptive(104.dp), Modifier.weight(1f).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(10.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                gridItems(names) { n ->
                    val have = anims.optJSONObject(n) != null
                    val on = n in picked
                    val sp = remember(id, ver, n) { Sprite().also { if (have) { it.load(f.parentFile!!); it.start(n) } } }
                    Column(Modifier.clip(RoundedCornerShape(16.dp)).background(PANEL).border(1.dp, if (on) ACCENT else LINE, RoundedCornerShape(16.dp))
                        .combinedClickable(onClick = { if (selecting) picked = if (on) picked - n else picked + n else { sel = n; detail = n } },
                            onLongClick = { selecting = true; picked = picked + n }).padding(8.dp),
                        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Box(Modifier.size(80.dp), contentAlignment = Alignment.Center) { if (have) Pet(tick, Modifier.fillMaxSize(), sp) else Text("—", color = DIM) }
                        Text(Sprite.label(n), fontSize = 12.sp, maxLines = 1, color = if (have) TEXT else DIM)
                    }
                }
            }
            return
        }
        BackHandler { detail = null }
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconBtn("‹", "Atrás") { detail = null }
            H1(j.optString("name", id))
        }
        Card(Modifier.fillMaxWidth().height(170.dp)) {
            if (a != null) Pet(tick, Modifier.fillMaxSize(), prev)
            else Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { Text("—", color = DIM) }
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(Sprite.label(sel), Modifier.weight(1f), fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
            Text((Sprite.WANTED[sel] ?: "").replaceFirstChar { it.uppercase() }, color = DIM, fontSize = 12.sp, maxLines = 1)
        }
        if (a != null) {
            val fps = a.optInt("fps", 8)
            val mode = if (a.optBoolean("pingpong")) "pingpong" else if (a.optBoolean("loop", true)) "loop" else "once"
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                IconBtn("−", "Menos fps", kind = "r", size = 40.dp) { save(fps - 1, mode) }
                Text("$fps fps", Modifier.width(56.dp), fontSize = 14.sp, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
                IconBtn("+", "Más fps", kind = "r", size = 40.dp) { save(fps + 1, mode) }
                Spacer(Modifier.weight(1f))
                listOf(Triple("loop", "🔁", "En bucle"), Triple("pingpong", "⇄", "Ida y vuelta"), Triple("once", "①", "Una vez")).forEach { (m, g, tip) ->
                    IconBtn(g, tip, on = m == mode, size = 40.dp) { save(fps, m) }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                IconBtn("▶", "Probar en la mascota", kind = "p") {
                    if (!OverlayService.running) return@IconBtn toast("Activa la mascota flotante (pestaña Cuidar)")
                    if (id != dir().name) return@IconBtn toast("Usa primero este personaje")
                    startService(Intent(this@MainActivity, OverlayService::class.java).setAction(OverlayService.PREVIEW).putExtra("anim", sel))
                }
                IconBtn(if (arm) "✓" else "🗑", if (arm) "¿Seguro? Toca otra vez" else "Eliminar", kind = "d") {
                    if (!arm) { arm = true; return@IconBtn }  // confirmación en dos toques, como el escritorio
                    anims.remove(sel)
                    f.writeText(j.toString(1))
                    toast("«${Sprite.label(sel)}» eliminada")
                    ver++
                    charVersion++
                    reloadFloat()
                }
            }
        }
    }

    /** Edita nombre, descripción, identidad y anatomía en character.json (se conservan los demás campos, como sprites.set_profile). */
    /** NewCharView: nombre, descripción, celda e imagen general opcional. Las animaciones se agregan en escritorio (aquí no hay generador). */
    @Composable
    private fun NewCharDialog(onClose: () -> Unit) {
        var name by remember { mutableStateOf("") }
        var desc by remember { mutableStateOf("") }
        var size by remember { mutableStateOf("192x208") }
        var img by remember { mutableStateOf<Uri?>(null) }
        val pick = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { if (it != null) img = it }
        AlertDialog(onDismissRequest = onClose, containerColor = PANEL,
            title = { Text("Nuevo personaje") },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    for ((label, value, set) in listOf(Triple("Nombre", name) { v: String -> name = v }, Triple("Descripción visual", desc) { v: String -> desc = v },
                        Triple("Celda (ancho×alto)", size) { v: String -> size = v }))
                        OutlinedTextField(value, set, Modifier.fillMaxWidth(), label = { Text(label) }, singleLine = label != "Descripción visual",
                            shape = RoundedCornerShape(12.dp), colors = fieldColors())
                    IconBtn(if (img == null) "🖼" else "✓", "Imagen general (opcional)", kind = "r") { pick.launch(arrayOf("image/*")) }
                }
            },
            confirmButton = {
                IconBtn("✓", "Crear", kind = "p") {
                    if (name.isBlank()) return@IconBtn toast("Ponle un nombre")
                    val cell = size.lowercase().split("x", "×").mapNotNull { it.trim().toIntOrNull() }
                    if (cell.size != 2) return@IconBtn toast("El tamaño debe verse así: 192x208")
                    try {
                        val id = createChar(name.trim(), desc.trim(), cell, img)
                        if (listChars().size == 1) useChar(id) else charVersion++
                        toast("Creado: ${name.trim()}")
                        onClose()
                    } catch (e: Exception) {
                        toast("No se pudo crear: ${e.message}")
                    }
                }
            },
            dismissButton = { IconBtn("✕", "Cancelar", onClick = onClose) })
    }

    /** Como sprites.create + set_source: character.json (se conservan los demás campos si ya existía), brief.md y source.png opcional. */
    private fun createChar(name: String, desc: String, cell: List<Int>, img: Uri?): String {
        val id = slug(name)
        val d = File(charsDir(this), id).apply { mkdirs() }
        val f = File(d, "character.json")
        val j = runCatching { JSONObject(f.readText()) }.getOrDefault(JSONObject())
        j.put("name", name).put("description", desc).put("cell", JSONArray(cell))
        if (!j.has("anims")) j.put("anims", JSONObject())
        f.writeText(j.toString(1))
        File(d, "brief.md").writeText(desc + "\n")
        img?.let { saveSource(d, it) }
        return id
    }

    /** Imagen general del personaje (sprites.set_source): cualquier imagen, guardada como source.png. */
    private fun saveSource(d: File, u: Uri) {
        val b = contentResolver.openInputStream(u)!!.use { BitmapFactory.decodeStream(it) } ?: throw Exception("no es una imagen válida")
        File(d, "source.png").outputStream().use { b.compress(Bitmap.CompressFormat.PNG, 100, it) }
    }

    @Composable
    private fun EditCharDialog(id: String, onClose: () -> Unit) {
        val f = File(File(charsDir(this), id), "character.json")
        val j = remember(id) { JSONObject(f.readText()) }
        val keys = listOf("name" to "Nombre", "description" to "Descripción", "personality" to "Personalidad (chat)", "story" to "Historia (opcional)",
            "identity" to "Identidad visual", "anatomy" to "Anatomía y movimiento")
        val values = remember(id) { keys.map { (k, _) -> mutableStateOf(j.optString(k, if (k == "name") id else "")) } }
        var gender by remember(id) { mutableStateOf(j.optString("gender")) }  // voz con la que responde (Speech)
        val scope = rememberCoroutineScope()
        var working by remember { mutableStateOf("") }
        val src = File(f.parentFile, "source.png")
        var hasSrc by remember(id) { mutableStateOf(src.isFile) }
        val pick = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { u ->
            if (u != null) try { saveSource(src.parentFile!!, u); hasSrc = true; toast("Imagen general guardada") } catch (e: Exception) { toast("No se pudo: ${e.message}") }
        }
        // personalidad buscada en la red o deducida de la historia (como fruquis/personality.py); queda en el campo para revisarla antes de guardar
        fun persona(fromStory: Boolean) {
            val story = values[3].value
            if (fromStory && story.isBlank()) return toast("Escribe primero la historia del personaje")
            working = if (fromStory) "Leyendo la historia…" else "Buscando en internet…"
            scope.launch {
                try {
                    values[2].value = withContext(Dispatchers.IO) { Persona.generate(this@MainActivity, values[0].value.trim(), values[1].value.trim(), if (fromStory) story else "") }
                } catch (e: Exception) {
                    toast(e.message ?: "No pude obtener la personalidad")
                }
                working = ""
            }
        }
        AlertDialog(onDismissRequest = onClose, containerColor = PANEL,
            title = { Text("Editar personaje") },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    // imagen general y hoja neutral (en escritorio, misma vista «Editar personaje»); la hoja neutral se genera en escritorio
                    Row(horizontalArrangement = Arrangement.spacedBy(4.dp), verticalAlignment = Alignment.CenterVertically) {
                        IconBtn(if (hasSrc) "✓" else "🖼", "Imagen general", kind = "r") { pick.launch(arrayOf("image/*")) }
                        Spacer(Modifier.weight(1f))
                        for ((k, g, tip) in listOf(Triple("", "∅", "Voz del sistema"), Triple("masculino", "♂", "Voz masculina"), Triple("femenino", "♀", "Voz femenina")))
                            IconBtn(g, tip, on = gender == k) { gender = k }
                    }
                    keys.forEachIndexed { i, (_, label) ->
                        OutlinedTextField(values[i].value, { values[i].value = it }, Modifier.fillMaxWidth(), label = { Text(label) }, singleLine = i == 0,
                            shape = RoundedCornerShape(12.dp), colors = fieldColors(), maxLines = if (i == 3) 6 else Int.MAX_VALUE)
                        if (i == 3) Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            if (working.isNotEmpty()) Text(working, color = DIM)
                            else {
                                IconBtn("🌐", "Buscar la personalidad en la red", kind = "r") { persona(false) }
                                IconBtn("📖", "Sacar la personalidad de la historia", kind = "r") { persona(true) }
                            }
                        }
                    }
                }
            },
            confirmButton = {
                IconBtn("✓", "Guardar", kind = "p") {
                    val name = values[0].value.trim()
                    if (name.isEmpty()) return@IconBtn toast("El nombre no puede estar vacío")
                    keys.forEachIndexed { i, (k, _) -> j.put(k, values[i].value.trim()) }
                    j.put("gender", gender)
                    f.writeText(j.toString(1))
                    charVersion++
                    onClose()
                }
            },
            dismissButton = { IconBtn("✕", "Cancelar", onClick = onClose) })
    }

    /** Ajustes de IA por API (en Android no hay binarios claude/codex). Mismas claves que Ai.kt. */
    @Composable
    private fun androidx.compose.foundation.layout.ColumnScope.SettingsTab() {
        val ai = remember { Ai(getSharedPreferences("ai", MODE_PRIVATE)) }
        val fields = listOf(
            Triple("chat", "kind", "Formato (openai | anthropic | server)"), Triple("chat", "url", "URL base (vacío = oficial) o enlace personal del servidor"),
            Triple("chat", "key", "Clave"), Triple("chat", "model", "Modelo (vacío = predeterminado)"),
            Triple("image", "kind", "Formato (openai | server)"), Triple("image", "url", "URL base (vacío = OpenAI) o enlace personal del servidor"), Triple("image", "key", "Clave"),
            Triple("image", "model", "Modelo (vacío = gpt-image-1)"))
        val values = remember { fields.map { (w, k, _) -> mutableStateOf(ai.p.getString("${w}_$k", "")!!) } }
        val app = remember { getSharedPreferences("app", MODE_PRIVATE) }
        var scale by remember { mutableStateOf(app.getFloat("scale", 0.6f)) }
        val lk = remember { Link.conf(this@MainActivity) }
        var lCode by remember { mutableStateOf(lk.code) }
        var lName by remember { mutableStateOf(lk.name) }
        var lRelay by remember { mutableStateOf(lk.relay.ifEmpty { if (ai.p.getString("chat_kind", "") == "server") ai.p.getString("chat_url", "")!! else "" }) }
        var lAccept by remember { mutableStateOf(lk.accept) }
        var lJoin by remember { mutableStateOf("") }
        var lState by remember { mutableStateOf("") }
        val scope = rememberCoroutineScope()
        LaunchedEffect(lCode) { while (true) { lState = Link.status(this@MainActivity); delay(2000) } }
        fun saveLink() {  // guarda nombre, enlace, código y modo de aceptación, y (re)inicia el servicio
            Link.save(this@MainActivity, code = lCode, name = lName.trim(), relay = lRelay.trim(), accept = lAccept)
            if (lCode.isNotEmpty()) startLink()
        }
        val filePicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
            if (uri != null) scope.launch {
                toast(withContext(Dispatchers.IO) {
                    try {
                        val name = contentResolver.query(uri, null, null, null, null)?.use { q ->
                            if (q.moveToFirst()) q.getString(q.getColumnIndexOrThrow(android.provider.OpenableColumns.DISPLAY_NAME)) else null } ?: "archivo"
                        val bytes = contentResolver.openInputStream(uri)!!.use { it.readBytes() }
                        "📤 «$name» enviado (por ${Link.sendFile(this@MainActivity, name, bytes)})"
                    } catch (e: Exception) { "📤 No pude enviarlo: ${e.message}" }
                })
            }
        }
        var speak by remember { mutableStateOf(Speech.on(this@MainActivity)) }
        var control by remember { mutableStateOf(app.getBoolean("control", false)) }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.weight(1f)) { H1("Ajustes") }
            IconBtn("✓", "Guardar", kind = "p") {
                ai.p.edit().apply { fields.forEachIndexed { i, (w, k, _) -> putString("${w}_$k", values[i].value.trim()) } }.apply()
                saveLink()
                toast("Ajustes guardados")
            }
        }
        // grupos plegables: la pantalla es una lista corta de cards y solo se abre lo que se necesita
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Group("🐾", "Mascota") {  // tamaño de la mascota flotante, como «Tamaño» del escritorio (store "scale", 30–120 %)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Slider(scale, { scale = it }, Modifier.weight(1f), valueRange = 0.3f..1.2f,
                        onValueChangeFinished = { app.edit().putFloat("scale", (scale * 100).toInt() / 100f).apply(); reloadFloat() },
                        colors = SliderDefaults.colors(thumbColor = ACCENT, activeTrackColor = ACCENT, inactiveTrackColor = RAISED))
                    Text("${(scale * 100).toInt()}%", Modifier.width(48.dp), color = DIM, fontSize = 13.sp)
                }
            }
            Group("🎙", "Asistente") {
                SwitchRow("Responder con voz", speak) {  // como «Responder con voz» del escritorio
                    speak = it
                    app.edit().putBoolean("speak", speak).apply()
                    if (!speak) tts?.stop()
                }
                SwitchRow("Controlar el teléfono", control) {  // como «Controlar» del escritorio
                    control = it
                    app.edit().putBoolean("control", control).apply()
                    if (control && PhoneService.instance == null) {  // el servicio de accesibilidad se activa a mano en Ajustes del sistema
                        toast("Activa «Fruquis» en Accesibilidad. Si sale gris: Info de la app › ⋮ › Permitir ajustes restringidos")
                        startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
                    }
                }
                Row(verticalAlignment = Alignment.CenterVertically) {  // botón lateral / gesto del asistente: Fruquis como «App de asistente digital» (AssistActivity)
                    Text("Asistente del teléfono", Modifier.weight(1f))
                    IconBtn("⚙", "Elegir Fruquis como asistente del teléfono", kind = "r", size = 40.dp) {
                        if (checkSelfPermission("android.permission.RECORD_AUDIO") != PackageManager.PERMISSION_GRANTED)
                            requestPermissions(arrayOf("android.permission.RECORD_AUDIO"), 3)
                        toast("Elige Fruquis en «App de asistente digital»")
                        startActivity(Intent(Settings.ACTION_MANAGE_DEFAULT_APPS_SETTINGS))
                    }
                }
            }
            Group("💬", "Chat (API)") { for (i in 0..3) ApiField(values[i], fields[i].third, fields[i].second == "key") }
            Group("🖼", "Imágenes (API)") { for (i in 4..7) ApiField(values[i], fields[i].third, fields[i].second == "key") }
            Group("🔗", "Otro equipo") {  // Link.kt: mismo código en los dos; en la misma red se conectan solos, entre redes hace falta el enlace del servidor aipi
                Text(if (lCode.isEmpty()) "Sin vincular" else "Código: ${Link.showCode(lCode)}", fontWeight = FontWeight.SemiBold)
                OutlinedTextField(lName, { lName = it }, Modifier.fillMaxWidth(), label = { Text("Nombre de este equipo") }, singleLine = true,
                    shape = RoundedCornerShape(12.dp), colors = fieldColors())
                OutlinedTextField(lRelay, { lRelay = it }, Modifier.fillMaxWidth(), label = { Text("Enlace del servidor aipi (?key=…) · vacío = misma red") }, singleLine = true,
                    shape = RoundedCornerShape(12.dp), colors = fieldColors())
                Row(horizontalArrangement = Arrangement.spacedBy(4.dp), verticalAlignment = Alignment.CenterVertically) {
                    IconBtn(when (lAccept) { "auto" -> "⚡"; "off" -> "⛔"; else -> "❓" },
                        when (lAccept) { "auto" -> "Sus órdenes se ejecutan sin preguntar"; "off" -> "No acepto órdenes del otro equipo"; else -> "Pregunto antes de ejecutar sus órdenes" }, kind = "r") {
                        lAccept = when (lAccept) { "ask" -> "auto"; "auto" -> "off"; else -> "ask" }
                    }
                    IconBtn("＋", "Crear vínculo nuevo", kind = "p") {
                        lCode = Link.newCode()
                        saveLink()
                        toast("Escribe ese código en el otro equipo")
                    }
                    if (lCode.isNotEmpty()) {
                        IconBtn("⇪", "Enviar un archivo al otro equipo", kind = "r") { filePicker.launch(arrayOf("*/*")) }
                        IconBtn("✕", "Desvincular", kind = "d") {
                            Link.save(this@MainActivity, code = "")
                            getSharedPreferences("link", MODE_PRIVATE).edit().remove("peers").apply()
                            lCode = ""
                            stopService(Intent(this@MainActivity, LinkService::class.java))
                        }
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    OutlinedTextField(lJoin, { lJoin = it }, Modifier.weight(1f), label = { Text("Código del otro equipo") }, singleLine = true,
                        shape = RoundedCornerShape(12.dp), colors = fieldColors())
                    IconBtn("🔗", "Unirme con este código", kind = "r") {
                        val code = Link.cleanCode(lJoin)
                        if (code.length != 12) return@IconBtn toast("El código tiene 12 letras o números (ABCD-EFGH-JKMN)")
                        lCode = code; lJoin = ""
                        saveLink()
                    }
                }
                if (lCode.isNotEmpty()) Text(lState, color = DIM, fontSize = 12.sp)
            }
        }
    }

    /** Card plegable: título con icono y, al tocarla, su contenido. */
    @Composable
    private fun Group(glyph: String, title: String, content: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit) {
        var open by remember { mutableStateOf(false) }
        Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(PANEL)) {
            Row(Modifier.fillMaxWidth().clickable { open = !open }.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(glyph, fontSize = 20.sp)
                Text(title, Modifier.weight(1f).padding(start = 12.dp), fontWeight = FontWeight.SemiBold)
                Text(if (open) "⌃" else "⌄", color = DIM)
            }
            if (open) Column(Modifier.padding(start = 16.dp, end = 16.dp, bottom = 16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) { content() }
        }
    }

    @Composable
    private fun SwitchRow(label: String, on: Boolean, onChange: (Boolean) -> Unit) = Row(verticalAlignment = Alignment.CenterVertically) {
        Text(label, Modifier.weight(1f))
        Switch(on, onChange, colors = SwitchDefaults.colors(checkedTrackColor = ACCENT, checkedThumbColor = Color.White))
    }

    @Composable
    private fun ApiField(v: androidx.compose.runtime.MutableState<String>, hint: String, secret: Boolean) =
        OutlinedTextField(v.value, { v.value = it }, Modifier.fillMaxWidth(), label = { Text(hint) }, singleLine = true,
            shape = RoundedCornerShape(12.dp), colors = fieldColors(),
            visualTransformation = if (secret) PasswordVisualTransformation() else VisualTransformation.None,
            keyboardOptions = KeyboardOptions(keyboardType = if (secret) KeyboardType.Password else KeyboardType.Text))

    @Composable
    private fun fieldColors() = OutlinedTextFieldDefaults.colors(focusedContainerColor = PANEL, unfocusedContainerColor = PANEL,
        unfocusedBorderColor = LINE, focusedBorderColor = ACCENT, cursorColor = ACCENT, focusedLabelColor = ACCENT, unfocusedLabelColor = DIM)

    private fun useChar(id: String) {
        setActive(this, id)
        chat.clear()  // otro personaje: chat nuevo
        charVersion++
        toast("Ahora es ${listChars()[id] ?: id}")
        reloadFloat()
    }

    /** Imagen adjunta lista para la API: reducida a 1280 px como máximo y en JPEG, para no mandar fotos enormes. */
    private fun jpeg(uri: Uri): ByteArray {
        val src = contentResolver.openInputStream(uri)!!.use { BitmapFactory.decodeStream(it) } ?: throw Exception("no es una imagen válida")
        val s = minOf(1f, 1280f / maxOf(src.width, src.height))
        val bmp = if (s < 1f) Bitmap.createScaledBitmap(src, (src.width * s).toInt(), (src.height * s).toInt(), true) else src
        return ByteArrayOutputStream().also { bmp.compress(Bitmap.CompressFormat.JPEG, 85, it) }.toByteArray()
    }

    /** Borra el personaje; si era el activo, `activeDir` cae al primero que quede y la mascota flotante se recarga. */
    private fun deleteChar(id: String) {
        val name = listChars()[id] ?: id
        if (!File(charsDir(this), id).deleteRecursively()) return toast("No se pudo eliminar")
        charVersion++
        toast("Eliminado: $name")
        reloadFloat()
    }

    // ---- mascota flotante (OverlayService) ----
    private fun toggleFloat() {
        if (OverlayService.running) {
            startService(Intent(this, OverlayService::class.java).setAction(OverlayService.STOP))
            floating = false
            return
        }
        if (!File(dir(), "character.json").exists()) return toast("Importa primero un personaje")
        if (!Settings.canDrawOverlays(this)) {  // permiso especial «Mostrar sobre otras apps»: se concede en una pantalla de Ajustes
            toast("Activa «Mostrar sobre otras apps» para Fruquis y vuelve")
            startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
            return
        }
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission("android.permission.POST_NOTIFICATIONS") != PackageManager.PERMISSION_GRANTED)
            requestPermissions(arrayOf("android.permission.POST_NOTIFICATIONS"), 2)  // para ver el aviso con el botón «Quitar»
        startForegroundService(Intent(this, OverlayService::class.java))
        floating = true
        if (!getSystemService(android.os.PowerManager::class.java).isIgnoringBatteryOptimizations(packageName))  // que el ahorro de batería no la cierre
            startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
    }

    /** Mismo zip que sprites.export_character: <id>/character.json, brief.md, imágenes de referencia y las hojas que usa. */
    private fun exportZip(id: String, out: java.io.OutputStream) {
        val d = File(charsDir(this), id)
        val anims = JSONObject(File(d, "character.json").readText()).optJSONObject("anims") ?: JSONObject()
        val sheets = anims.keys().asSequence().map { File(anims.getJSONObject(it).getString("sheet")).name }.toSortedSet()
        ZipOutputStream(out).use { z ->
            (listOf("character.json", "brief.md", "reference.png", "source.png", "neutral.png") + sheets).map { File(d, it) }.filter { it.isFile }.forEach {
                z.putNextEntry(ZipEntry("$id/${it.name}"))
                it.inputStream().use { i -> i.copyTo(z) }
                z.closeEntry()
            }
        }
    }

    /** Extrae solo .json/.png/.md y por nombre de archivo (el zip trae <id>/<archivo>): no hay rutas que escapen de la carpeta. */
    private fun importZip(input: InputStream): String {
        val tmp = File(filesDir, "character.tmp")
        tmp.deleteRecursively()
        tmp.mkdirs()
        var root = ""
        ZipInputStream(input).use { z ->
            var total = 0L
            generateSequence { z.nextEntry }.forEach { e ->
                if (root.isEmpty() && e.name.contains('/')) root = e.name.substringBefore('/')
                val n = File(e.name).name
                if (e.isDirectory || !Regex("[\\w.\\- ]+\\.(json|png|md)").matches(n)) return@forEach
                File(tmp, n).outputStream().use { o ->
                    val buf = ByteArray(8192)
                    while (true) {
                        val r = z.read(buf)
                        if (r <= 0) break
                        total += r
                        if (total > 200L shl 20) throw Exception("zip demasiado grande")
                        o.write(buf, 0, r)
                    }
                }
            }
        }
        if (!File(tmp, "character.json").exists()) { tmp.deleteRecursively(); throw Exception("falta character.json") }
        // mismo id que sprites.import_character: carpeta raíz del zip (o el nombre), con sufijo -2, -3… si ya existe
        val base = slug(root.ifEmpty { JSONObject(File(tmp, "character.json").readText()).optString("name", "personaje") })
        val taken = listChars().keys
        var id = base
        var k = 2
        while (id in taken) id = "$base-${k++}"
        if (!tmp.renameTo(File(charsDir(this), id))) throw Exception("no se pudo guardar")
        return id
    }
}
