from datetime import time

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Configuracion(models.Model):
    """Parámetros generales (un solo renglón). Se cambian en Catálogos."""

    turno_inicio = models.TimeField(default=time(8, 30), verbose_name="Inicio del turno")
    turno_fin = models.TimeField(default=time(18, 0), verbose_name="Fin del turno")
    comida_minutos = models.PositiveIntegerField(
        default=60, validators=[MaxValueValidator(600)], verbose_name="Comida (min)",
    )
    tolerancia_pct = models.PositiveIntegerField(
        default=15, validators=[MinValueValidator(1), MaxValueValidator(100)], verbose_name="Tolerancia (%)",
    )
    minimo_medidas = models.PositiveIntegerField(
        default=3, validators=[MinValueValidator(1), MaxValueValidator(50)], verbose_name="Mínimo de medidas",
    )

    class Meta:
        verbose_name = "Configuración"
        verbose_name_plural = "Configuración"

    def __str__(self):
        return "Configuración general"

    @classmethod
    def actual(cls):
        return cls.objects.get_or_create(pk=1)[0]

    @property
    def turno_minutos(self):
        """8:30 a 18:00 menos 1 h de comida = 510."""
        inicio = self.turno_inicio.hour * 60 + self.turno_inicio.minute
        fin = self.turno_fin.hour * 60 + self.turno_fin.minute
        return max(fin - inicio - self.comida_minutos, 0)
