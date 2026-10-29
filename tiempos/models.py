from decimal import Decimal
from django.db import models
from django.utils import timezone
from designaciones.models import Operario, Maquina, OperacionMadre, OperacionDetallada


def mmss_a_minutos(cadena_mmss):
    """Convierte texto 'mm:ss' (ej. 01:18) a minutos decimales (1.30)"""
    if not cadena_mmss:
        return Decimal("0.0")
    try:
        partes = str(cadena_mmss).strip().split(":")
        if len(partes) == 2:
            minutos = Decimal(partes[0])
            segundos = Decimal(partes[1])
            return round(minutos + (segundos / Decimal("60.0")), 3)
        return round(Decimal(cadena_mmss), 3)
    except Exception:
        return Decimal("0.0")


class MedicionTiempo(models.Model):
    MATERIAL_CHOICES = [
        ("F", "Fierro"),
        ("I", "Inox"),
        ("O", "Otro / N/A"),
    ]

    fecha = models.DateField(default=timezone.localdate, verbose_name="Fecha")
    quien_midio = models.CharField(max_length=80, verbose_name="Quién midió (Analista)")
    operador = models.ForeignKey(
        Operario, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Operador"
    )
    modelo_pieza = models.CharField(max_length=150, verbose_name="Modelo / Pieza")
    operacion_madre = models.ForeignKey(
        OperacionMadre, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Op. madre"
    )
    operacion_detallada = models.ForeignKey(
        OperacionDetallada, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Op. detallada"
    )
    maquina = models.ForeignKey(
        Maquina, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Máquina"
    )
    medida = models.CharField(max_length=50, blank=True, default="", verbose_name="Medida")
    material = models.CharField(max_length=1, choices=MATERIAL_CHOICES, default="F", verbose_name="Material")

    tiempo_1_pieza = models.CharField(max_length=10, verbose_name="1 pieza (mm:ss)", default="00:00")
    muestra_piezas = models.PositiveIntegerField(default=1, verbose_name="Muestra (piezas)")
    muestra_tiempo_total = models.CharField(max_length=10, verbose_name="Tiempo total muestra (mm:ss)", default="00:00")

    foto_url = models.URLField(blank=True, default="", verbose_name="Link de evidencia / foto")
    observaciones = models.TextField(blank=True, default="", verbose_name="Observaciones")
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "Medición de tiempo"
        verbose_name_plural = "Mediciones de tiempos"

    def __str__(self):
        return f"{self.modelo_pieza} ({self.fecha})"

    # ===== FÓRMULAS DEL EXCEL =====
    @property
    def minutos_muestra_decimal(self):
        """Columna O: Min/pz de la muestra"""
        total_min = mmss_a_minutos(self.muestra_tiempo_total)
        if self.muestra_piezas > 0:
            return round(total_min / Decimal(self.muestra_piezas), 2)
        return Decimal("0.0")

    @property
    def teorico_minutos(self):
        """Columna M: Tiempo teórico en minutos"""
        t1 = mmss_a_minutos(self.tiempo_1_pieza)
        return round(t1 * Decimal(self.muestra_piezas), 2)

    @property
    def porcentaje_dif(self):
        """Columna N: % dif vs teórico"""
        teorico = self.teorico_minutos
        if teorico > 0:
            total_real = mmss_a_minutos(self.muestra_tiempo_total)
            dif = (total_real - teorico) / teorico
            return round(dif * Decimal("100.0"), 1)
        return Decimal("0.0")

    @property
    def min_pz_hoy(self):
        """Columna P: Min/pz estándar registrado actualmente en el sistema"""
        if self.operacion_detallada and self.operacion_detallada.minutos_estandar:
            return self.operacion_detallada.minutos_estandar
        return "NUEVA"

    @property
    def estatus_tolerancia(self):
        """Evalúa si la muestra entra dentro de la tolerancia de ±10%"""
        std = self.min_pz_hoy
        if std == "NUEVA":
            return {"texto": "NUEVA", "clase": "bg-purple text-white"}
        
        real = self.minutos_muestra_decimal
        std_dec = Decimal(str(std))
        if std_dec > 0:
            desviacion = abs((real - std_dec) / std_dec)
            if desviacion <= Decimal("0.10"):
                return {"texto": "EN TOLERANCIA", "clase": "status-terminado"}
            return {"texto": "DESVIADO", "clase": "status-detenido"}
        return {"texto": "SIN ESTÁNDAR", "clase": "status-neutral"}