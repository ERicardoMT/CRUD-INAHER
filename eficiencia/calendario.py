"""Días hábiles: lunes a viernes, sin festivos oficiales ni los días que cierra la planta (Catálogos)."""
from datetime import date, timedelta
from functools import lru_cache

from core.models import DiaInhabil


def _lunes(anio, mes, numero):
    """El n-ésimo lunes del mes (1 = primero)."""
    dia = date(anio, mes, 1)
    dia += timedelta(days=-dia.weekday() % 7)
    return dia + timedelta(weeks=numero - 1)


@lru_cache(maxsize=32)
def festivos_oficiales(anio):
    """Ley Federal del Trabajo, art. 74."""
    dias = {
        date(anio, 1, 1), _lunes(anio, 2, 1), _lunes(anio, 3, 3), date(anio, 5, 1),
        date(anio, 9, 16), _lunes(anio, 11, 3), date(anio, 12, 25),
    }
    if (anio - 2024) % 6 == 0:  # 1 oct, cambio del Poder Ejecutivo federal (2024, 2030…)
        dias.add(date(anio, 10, 1))
    return frozenset(dias)


class Calendario:
    """Lee una sola vez de la base los días que cierra la planta y responde rápido."""

    def __init__(self):
        self.cerrados = set(DiaInhabil.objects.values_list("fecha", flat=True))

    def es_habil(self, dia):
        return dia.weekday() < 5 and dia not in festivos_oficiales(dia.year) and dia not in self.cerrados

    def siguiente_habil(self, dia):
        while not self.es_habil(dia):
            dia += timedelta(days=1)
        return dia

    def dias_de_carga(self, hoy, siguientes=9):
        """Hoy y los nueve días hábiles siguientes."""
        dias = [hoy]
        while len(dias) <= siguientes:
            dias.append(self.siguiente_habil(dias[-1] + timedelta(days=1)))
        return dias

    def habiles_entre(self, desde, hasta):
        if not (desde and hasta):
            return 0
        return sum(1 for i in range((hasta - desde).days + 1) if self.es_habil(desde + timedelta(days=i)))
