package com.ojitos369.fruquis

import android.content.SharedPreferences
import androidx.compose.runtime.mutableStateListOf

/** Tamagotchi: hambre, limpieza, diversión y energía (0-100). Paridad con fruquis/care.py (DECAY, FLOOR, ACTIONS). */
class Care(private val prefs: SharedPreferences) {
    class Action(val label: String, val anim: String, val fx: IntArray, val icon: String)  // fx: hambre, limpieza, diversión, energía

    val stats = mutableStateListOf(80.0, 80.0, 80.0, 80.0)  // observable por la interfaz

    init { load() }

    /** Lee lo guardado y aplica el tiempo que estuvo cerrada la app: nada baja de FLOOR por ausencia. */
    fun load() {
        val at = prefs.getLong("at", System.currentTimeMillis())
        KEYS.forEachIndexed { i, k -> stats[i] = prefs.getFloat(k, 80f).toDouble() }
        advance((System.currentTimeMillis() - at) / 1000.0, true)
    }

    fun advance(seconds: Double, offline: Boolean) {
        for (i in 0 until 4) {
            val v = stats[i] - DECAY[i] * seconds / 3600
            stats[i] = if (offline) maxOf(minOf(stats[i], FLOOR), v) else maxOf(0.0, v)
        }
        save()
    }

    fun act(a: Action) {
        for (i in 0 until 4) stats[i] = (stats[i] + a.fx[i]).coerceIn(0.0, 100.0)
        save()
    }

    private fun save() = prefs.edit().apply {
        putLong("at", System.currentTimeMillis())
        KEYS.forEachIndexed { i, k -> putFloat(k, stats[i].toFloat()) }
    }.apply()

    companion object {
        val KEYS = listOf("hambre", "limpieza", "diversion", "energia")
        val ICONS = listOf("🍙", "🫧", "🎾", "⚡")
        val NAMES = listOf("Hambre", "Limpieza", "Diversión", "Energía")
        private val DECAY = doubleArrayOf(6.0, 4.0, 5.0, 2.0)  // puntos por hora
        private const val FLOOR = 15.0
        val ACTIONS = listOf(
            Action("Comer", "eating", intArrayOf(35, -5, 0, 0), "🍙"), Action("Limpiar", "cleaning", intArrayOf(0, 50, 0, 0), "🫧"),
            Action("Jugar", "playing", intArrayOf(-5, 0, 30, -8), "🎾"), Action("Mimar", "pampered", intArrayOf(0, 0, 25, 3), "💜"),
            Action("Dormir", "sleeping", intArrayOf(-3, 0, 0, 40), "💤"))
    }
}
