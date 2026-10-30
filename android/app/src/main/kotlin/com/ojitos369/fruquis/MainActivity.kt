package com.ojitos369.fruquis

import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameMillis
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.InputStream
import java.util.zip.ZipInputStream

/** Animación a reproducir; cada instancia es distinta, así que relanza la animación aunque sea la misma. */
private class Play(val anim: String, val ms: Long)

/** Versión Android de Fruquis: la mascota animada con las mismas hojas de sprites (character.json) y el mismo tamagotchi que el escritorio.
 *  Mantener en paridad con fruquis/care.py (Care.kt) y con el formato de fruquis/sprites.py (Sprite.kt). La mascota flotante es OverlayService. */
class MainActivity : ComponentActivity() {
    private val care by lazy { Care(getSharedPreferences("care", MODE_PRIVATE)) }
    private val sprite = Sprite()
    private var charVersion by mutableStateOf(0)  // sube al importar un personaje
    private var floating by mutableStateOf(false)

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        enableEdgeToEdge()
        setContent { FruquisTheme { Surface(Modifier.fillMaxSize()) { Home() } } }
    }

    override fun onResume() {
        super.onResume()
        care.load()
        floating = OverlayService.running
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_LONG).show()

    private fun dir() = File(filesDir, "character")

    @Composable
    private fun FruquisTheme(content: @Composable () -> Unit) {
        val dark = androidx.compose.foundation.isSystemInDarkTheme()
        val ctx = LocalContext.current
        MaterialTheme(colorScheme = when {
            Build.VERSION.SDK_INT >= 31 -> if (dark) dynamicDarkColorScheme(ctx) else dynamicLightColorScheme(ctx)
            dark -> darkColorScheme()
            else -> lightColorScheme()
        }, content = content)
    }

    @Composable
    private fun Home() {
        var play by remember { mutableStateOf(Play("idle", 0)) }
        var reply by remember { mutableStateOf("") }
        var dialog by remember { mutableStateOf("") }  // "", "talk" o "ai"
        val scope = rememberCoroutineScope()
        val tick = remember { mutableLongStateOf(0) }

        val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
            if (uri != null) try {
                contentResolver.openInputStream(uri)!!.use { importZip(it) }
                charVersion++
                toast("Personaje importado")
            } catch (e: Exception) {
                toast("No se pudo importar: ${e.message}")
            }
        }

        LaunchedEffect(charVersion) { sprite.load(dir()); sprite.start(play.anim) }
        LaunchedEffect(play) {
            sprite.start(play.anim)
            if (play.ms > 0) { delay(play.ms); play = Play("idle", 0) }
        }
        LaunchedEffect(Unit) { while (true) { delay(60_000); care.advance(60.0, false) } }
        LaunchedEffect(Unit) { while (true) withFrameMillis { tick.longValue = it } }  // redibuja la mascota en cada cuadro

        Column(Modifier.safeDrawingPadding().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Canvas(Modifier.weight(1f).fillMaxWidth()) {
                tick.longValue  // lee el estado para que cada cuadro redibuje
                drawIntoCanvas { sprite.draw(it.nativeCanvas, size.width.toInt(), size.height.toInt()) }
            }
            if (reply.isNotEmpty()) Card(Modifier.fillMaxWidth()) {
                Text(reply, Modifier.heightIn(max = 140.dp).verticalScroll(rememberScrollState()).padding(12.dp))
            }
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Care.NAMES.forEachIndexed { i, n ->
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("${Care.ICONS[i]} $n", Modifier.padding(end = 4.dp), style = MaterialTheme.typography.labelMedium)
                        LinearProgressIndicator(progress = { (care.stats[i] / 100).toFloat() }, Modifier.weight(1f))
                    }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Care.ACTIONS.forEach { a ->
                    FilledTonalButton({ care.act(a); play = Play(a.anim, 3000) }, Modifier.weight(1f), contentPadding = androidx.compose.foundation.layout.PaddingValues(0.dp)) {
                        Text(a.icon)
                    }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton({ picker.launch(arrayOf("*/*")) }, Modifier.weight(1f)) { Text("Importar .zip") }
                Button({ toggleFloat() }, Modifier.weight(1f)) { Text(if (floating) "Quitar flotante" else "Flotante") }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton({ dialog = "talk" }, Modifier.weight(1f)) { Text("Hablar") }
                OutlinedButton({ dialog = "ai" }, Modifier.weight(1f)) { Text("Ajustes de IA") }
            }
        }

        when (dialog) {
            "talk" -> TalkDialog({ dialog = "" }) { text ->
                play = Play("talking", 120_000)
                scope.launch {
                    reply = withContext(Dispatchers.IO) {
                        try {
                            Ai(getSharedPreferences("ai", MODE_PRIVATE)).chat(text, "Eres Fruquis, una mascota tierna. Responde siempre en español, máximo 3 frases.")
                        } catch (e: Exception) {
                            "No pude responder (${e.message})"
                        }
                    }
                    play = Play("talking", 2000)
                }
            }
            "ai" -> AiDialog(Ai(getSharedPreferences("ai", MODE_PRIVATE))) { dialog = "" }
        }
    }

    @Composable
    private fun TalkDialog(onDismiss: () -> Unit, onSend: (String) -> Unit) {
        var text by remember { mutableStateOf("") }
        AlertDialog(onDismissRequest = onDismiss, title = { Text("Dile algo") },
            text = { OutlinedTextField(text, { text = it }, Modifier.fillMaxWidth()) },
            confirmButton = { TextButton({ onSend(text); onDismiss() }) { Text("Enviar") } },
            dismissButton = { TextButton(onDismiss) { Text("Cancelar") } })
    }

    @Composable
    private fun AiDialog(ai: Ai, onDismiss: () -> Unit) {
        val fields = listOf(
            Triple("chat", "kind", "Chat: formato (openai | anthropic)"), Triple("chat", "url", "Chat: URL base (vacío = oficial)"),
            Triple("chat", "key", "Chat: clave"), Triple("chat", "model", "Chat: modelo (vacío = predeterminado)"),
            Triple("image", "url", "Imágenes: URL base (vacío = OpenAI)"), Triple("image", "key", "Imágenes: clave"),
            Triple("image", "model", "Imágenes: modelo (vacío = gpt-image-1)"))
        val values = remember { fields.map { (w, k, _) -> mutableStateOf(ai.p.getString("${w}_$k", "")!!) } }
        AlertDialog(onDismissRequest = onDismiss, title = { Text("IA por API") },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    fields.forEachIndexed { i, (_, k, hint) ->
                        val secret = k == "key"
                        OutlinedTextField(values[i].value, { values[i].value = it }, Modifier.fillMaxWidth(), label = { Text(hint) }, singleLine = true,
                            visualTransformation = if (secret) PasswordVisualTransformation() else VisualTransformation.None,
                            keyboardOptions = KeyboardOptions(keyboardType = if (secret) KeyboardType.Password else KeyboardType.Text))
                    }
                }
            },
            confirmButton = {
                TextButton({
                    ai.p.edit().apply { fields.forEachIndexed { i, (w, k, _) -> putString("${w}_$k", values[i].value.trim()) } }.apply()
                    onDismiss()
                }) { Text("Guardar") }
            },
            dismissButton = { TextButton(onDismiss) { Text("Cancelar") } })
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
    }

    /** Extrae solo .json/.png/.md y por nombre de archivo (el zip trae <id>/<archivo>): no hay rutas que escapen de la carpeta. */
    private fun importZip(input: InputStream) {
        val tmp = File(filesDir, "character.tmp")
        tmp.deleteRecursively()
        tmp.mkdirs()
        ZipInputStream(input).use { z ->
            var total = 0L
            generateSequence { z.nextEntry }.forEach { e ->
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
        dir().deleteRecursively()
        if (!tmp.renameTo(dir())) throw Exception("no se pudo guardar")
    }
}
