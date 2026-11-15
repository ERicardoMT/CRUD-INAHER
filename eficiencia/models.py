from django.db import models

class CambioEstandar(models.Model):
    """Bitácora de cambios de estándar hechos desde Eficiencia › Por operación."""

    operacion = models.ForeignKey(
        "designaciones.OperacionDetallada", on_delete=models.PROTECT, related_name="cambios_estandar",
        verbose_name="Operación",
    )
    anterior = models.DecimalField(max_digits=7, decimal_places=2, verbose_name="Valor anterior")
    nuevo = models.DecimalField(max_digits=7, decimal_places=2, verbose_name="Valor nuevo")
    medidas = models.PositiveIntegerField(default=0, verbose_name="Medidas")
    usuario = models.CharField(max_length=150, verbose_name="Quién")
    fecha = models.DateTimeField(auto_now_add=True, verbose_name="Cuándo")

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "Cambio de estándar"
        verbose_name_plural = "Cambios de estándar"
        permissions = [
            ("capturar_tiempos", "Puede capturar Min real"),
            ("cambiar_estandar", "Puede cambiar el estándar"),
        ]

    def __str__(self):
        return f"{self.operacion} · {self.anterior} → {self.nuevo}"
