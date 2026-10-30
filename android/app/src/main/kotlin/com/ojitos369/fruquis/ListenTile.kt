package com.ojitos369.fruquis

import android.app.PendingIntent
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService

/** Mosaico «Escucha activa» en los ajustes rápidos (como girar pantalla o NFC): activa o desactiva la escucha del nombre (VoiceService LISTEN).
 *  Para encenderla pasa por AssistActivity: el micrófono en segundo plano solo se permite si la app estaba al frente al arrancar. */
class ListenTile : TileService() {
    override fun onStartListening() {
        qsTile?.apply {
            state = if (VoiceService.running) Tile.STATE_ACTIVE else Tile.STATE_INACTIVE
            if (Build.VERSION.SDK_INT >= 29) subtitle = if (VoiceService.running) "Di su nombre" else "Apagada"
            updateTile()
        }
    }

    override fun onClick() {
        if (VoiceService.running) {
            startService(Intent(this, VoiceService::class.java).setAction(VoiceService.STOP))
            return
        }
        val i = Intent(this, AssistActivity::class.java).setAction(VoiceService.LISTEN).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (Build.VERSION.SDK_INT >= 34) startActivityAndCollapse(PendingIntent.getActivity(this, 3, i, PendingIntent.FLAG_IMMUTABLE))
        else @Suppress("DEPRECATION") startActivityAndCollapse(i)
    }

    companion object {
        /** Que el mosaico vuelva a leer el estado (al encender o apagar la escucha). */
        fun refresh(c: Context) = runCatching { requestListeningState(c, ComponentName(c, ListenTile::class.java)) }
    }
}
