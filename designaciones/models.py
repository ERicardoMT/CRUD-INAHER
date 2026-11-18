from datetime import date
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F
from django.utils import timezone
from pedidos.models import PartidaPedido, Pedido

def clase_eficiencia(pct):
    """Verde 90 % o más · ámbar 75 a 89 · rojo menos de 75."""
    if pct is None:
        return ""
    if pct >= 90:
        return "efic-ok"
    return "efic-media" if pct >= 75 else "efic-baja"

def campo_tarifa():
    return models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0"))], verbose_name="Tarifa por hora ($)",
    )

class Operario(models.Model):
    nombre = models.CharField(max_length=100, unique=True, verbose_name="Nombre")
    activo = models.BooleanField(default=True, verbose_name="Activo")
    orden = models.PositiveIntegerField(default=0, verbose_name="Orden de visualización")
    tarifa_hora = campo_tarifa()

    class Meta:
        ordering = ["orden", "nombre"]
        verbose_name = "Operario"
        verbose_name_plural = "Operarios"

    def __str__(self):
        return self.nombre


class Maquina(models.Model):
    nombre = models.CharField(max_length=120, unique=True, verbose_name="Nombre de máquina")
    tipo = models.CharField(max_length=100, blank=True, verbose_name="Tipo de máquina")
    activa = models.BooleanField(default=True, verbose_name="Activa")
    tarifa_hora = campo_tarifa()

    class Meta:
        ordering = ["nombre"]
        verbose_name = "Máquina"
        verbose_name_plural = "Máquinas"

    def __str__(self):
        return self.nombre
    
    @property
    def es_manual(self):
        """Tipo "Manual" (ej. "Manual (mesa)"): no es una máquina, la hacen varias personas. No lleva minutos libres."""
        return self.tipo.strip().lower() == "manual"

class OperacionMadre(models.Model):
    nombre = models.CharField(max_length=150, unique=True, verbose_name="Operación madre")
    tipo_maquina = models.CharField(max_length=100, blank=True, verbose_name="Tipo de máquina sugerida")
    activa = models.BooleanField(default=True, verbose_name="Activa")

    class Meta:
        ordering = ["nombre"]
        verbose_name = "Operación madre"
        verbose_name_plural = "Operaciones madre"

    def __str__(self):
        return self.nombre


class OperacionDetallada(models.Model):
    madre = models.ForeignKey(
        OperacionMadre,
        on_delete=models.CASCADE,
        related_name="detalles",
        verbose_name="Operación madre",
    )
    nombre = models.CharField(max_length=200, verbose_name="Operación detallada")
    maquina_sugerida = models.ForeignKey(
        Maquina,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="operaciones",
        verbose_name="Máquina sugerida",
    )
    minutos_estandar = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        default=0.0,
        verbose_name="Minutos estándar por pieza",
    )
    activa = models.BooleanField(default=True, verbose_name="Activa")

    class Meta:
        ordering = ["madre__nombre", "nombre"]
        unique_together = ("madre", "nombre")
        verbose_name = "Operación detallada"
        verbose_name_plural = "Operaciones detalladas"

    def __str__(self):
        return f"{self.madre.nombre} › {self.nombre}"
    
    def minutos_fijos(self, cantidad):
        """Tiempo fijo o por escalones del catálogo (manda sobre el estudio). None si la operación no tiene."""
        fijo = getattr(self, "tiempo_fijo", None)
        if fijo:
            return round(fijo.minutos if fijo.por_pedido else fijo.minutos * cantidad)
        for escalon in self.escalones.all():  # ordenados por "hasta"; el último sin tope = "más de"
            if escalon.hasta is None or cantidad <= escalon.hasta:
                return round(escalon.minutos)
        return None

    def minutos_para(self, cantidad):
        """Normal: min/pz del estudio × cantidad. Sin tiempo: 0."""
        fijos = self.minutos_fijos(cantidad)
        return fijos if fijos is not None else round(self.minutos_estandar * cantidad)

    @property
    def es_por_pedido(self):
        """Empaquetar, Contar y revisar: tiempo por pedido, sin piezas por hora."""
        fijo = getattr(self, "tiempo_fijo", None)
        return bool(fijo and fijo.por_pedido) or bool(self.escalones.all())

class TiempoFijo(models.Model):
    """Tiempo fijo del catálogo; manda sobre el Estudio de tiempos (ej. Empaquetar pedido chico = 3 min por pedido)."""

    operacion = models.OneToOneField(
        OperacionDetallada, on_delete=models.CASCADE, related_name="tiempo_fijo", verbose_name="Operación detallada",
    )
    minutos = models.DecimalField(
        max_digits=7, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))], verbose_name="Minutos",
    )
    por_pedido = models.BooleanField(default=True, verbose_name="Por pedido (no se multiplica por la cantidad)")

    class Meta:
        ordering = ["operacion__nombre"]
        verbose_name = "Tiempo fijo"
        verbose_name_plural = "Tiempos fijos"

    def __str__(self):
        return f"{self.operacion.nombre} · {self.minutos} min {'por pedido' if self.por_pedido else 'por pieza'}"


class Escalon(models.Model):
    """Minutos por pedido según la cantidad (ej. Contar y revisar: hasta 999 → 3 · hasta 5,000 → 6 …)."""

    operacion = models.ForeignKey(
        OperacionDetallada, on_delete=models.CASCADE, related_name="escalones", verbose_name="Operación detallada",
    )
    hasta = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="Hasta (piezas)", help_text="Vacío = más de lo anterior.",
    )
    minutos = models.DecimalField(
        max_digits=7, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))], verbose_name="Minutos por pedido",
    )

    class Meta:
        ordering = ["operacion__nombre", F("hasta").asc(nulls_last=True)]
        verbose_name = "Escalón de tiempo"
        verbose_name_plural = "Escalones de tiempo"

    def __str__(self):
        tope = f"hasta {self.hasta:,}" if self.hasta is not None else "más"
        return f"{self.operacion.nombre} · {tope} → {self.minutos} min"

class DesignacionDia(models.Model):
    fecha = models.DateField(unique=True, default=timezone.localdate, verbose_name="Fecha de la jornada")
    molde_1 = models.CharField(max_length=150, blank=True, default="", verbose_name="Molde 1 (Vulcanizado)")
    molde_2 = models.CharField(max_length=150, blank=True, default="", verbose_name="Molde 2 (Vulcanizado)")
    notas = models.TextField(blank=True, default="", verbose_name="Notas de la jornada")
    cerrada = models.BooleanField(default=False, verbose_name="Jornada archivada / cerrada")
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "Designación del día"
        verbose_name_plural = "Designaciones de días"

    def __str__(self):
        return f"Designación {self.fecha.strftime('%d/%m/%Y')}"

    @property
    def total_minutos_asignados(self):
        return sum(item.minutos for item in self.items.all())

    @property
    def total_minutos_hechos(self):
        return sum(item.minutos for item in self.items.all() if item.hecho)

    @property
    def porcentaje_avance(self):
        total = self.total_minutos_asignados
        if total == 0:
            return 0
        return round((self.total_minutos_hechos / total) * 100)


class ItemDesignacion(models.Model):
    designacion = models.ForeignKey(
        DesignacionDia,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Jornada",
    )
    quien = models.ForeignKey(
        Operario,
        on_delete=models.PROTECT,
        related_name="items_designados",
        verbose_name="Quién",
    )
    pedido = models.ForeignKey(
        Pedido,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="items_designacion",
        verbose_name="# Pedido",
    )
    partida = models.ForeignKey(
        PartidaPedido,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="items_designacion",
        verbose_name="Partida",
        help_text="Vacío = tarea de todo el pedido (p. ej. Empaquetar, cuenta una vez).",
    )
    bloqueado_por = models.CharField(
        max_length=150,
        blank=True,
        default="",
        verbose_name="Bloqueada por material",
        help_text="Material faltante · fecha esperada. Si se llena, el pedido se marca DETENIDO solo.",
    )
    es_stock = models.BooleanField(
        default=False,
        verbose_name="Para stock",
    )
    paso = models.PositiveIntegerField(
        default=1,
        verbose_name="Paso",
    )
    descripcion_manual = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Producto / Modelo (manual o notas de stock)",
    )
    operacion_madre = models.ForeignKey(
        OperacionMadre,
        on_delete=models.PROTECT,
        verbose_name="Op. madre",
    )
    operacion_detallada = models.ForeignKey(
        OperacionDetallada,
        on_delete=models.PROTECT,
        verbose_name="Op. detallada",
    )
    maquina = models.ForeignKey(
        Maquina,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Máquina",
    )
    detalle = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Detalle (medida · tolerancia)",
    )
    cantidad = models.PositiveIntegerField(
        default=1,
        verbose_name="Cantidad",
    )
    piezas_hechas = models.PositiveIntegerField(
        default=0,
        blank=True,
        verbose_name="Piezas hechas",
        help_text="Las que lleva, acumuladas aunque se trabaje varios días.",
    )
    minutos = models.PositiveIntegerField(
        default=0,
        verbose_name="Minutos estimados",
    )
    hecho = models.BooleanField(
        default=False,
        verbose_name="Completado (✓)",
    )

    fecha_cierre = models.DateField(null=True, blank=True, db_index=True, verbose_name="Fecha de cierre")
    cerrada_al_archivar = models.BooleanField(default=False, verbose_name="✓ al archivar")

    # Eficiencia: único dato que se captura (solo administrador)
    min_real = models.DecimalField(
        max_digits=7, decimal_places=1, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.1"))], verbose_name="Min real",
    )
    min_real_por = models.CharField(max_length=150, blank=True, default="", verbose_name="Midió")
    min_real_en = models.DateTimeField(null=True, blank=True, verbose_name="Medido el")

    orden = models.PositiveIntegerField(
        default=0,
        verbose_name="Orden",
    )

    class Meta:
        ordering = ["orden", "id"]
        verbose_name = "Tarea de designación"
        verbose_name_plural = "Tareas de designación"

    def __str__(self):
        return f"{self.quien.nombre} - Paso {self.paso} ({self.operacion_detallada.nombre})"

    def save(self, *args, **kwargs):
        # Minuto estándar (regla D): tiempo fijo o escalones mandan; si no, min/pz × cantidad (sin tiempo = 0)
        if kwargs.get("update_fields") is None and self.operacion_detallada_id:
            fijos = self.operacion_detallada.minutos_fijos(self.cantidad)
            if fijos is not None:
                self.minutos = fijos
            elif not self.minutos:
                self.minutos = self.operacion_detallada.minutos_para(self.cantidad)
        super().save(*args, **kwargs)

    @property
    def producto_texto(self):
        if self.es_stock:
            return "Para stock (ver Detalle)"
        if self.pedido:
            return self.pedido.descripcion
        if self.descripcion_manual:
            return self.descripcion_manual
        return "NO ESTÁ EN PEDIDOS"

    @property
    def producto_cerrado(self):
        """Producto en el historial: la partida si la tiene; si no, el texto de siempre."""
        return self.partida.descripcion if self.partida else self.producto_texto
  
    # ----- Eficiencia (solo si se capturó Min real) -----
    @property
    def eficiencia(self):
        """Min estándar ÷ min real, en %. Sin Min real o sin estándar no cuenta."""
        if not self.min_real or not self.minutos:
            return None
        return round(self.minutos * 100 / self.min_real)

    @property
    def eficiencia_clase(self):
        return clase_eficiencia(self.eficiencia)

    @property
    def pzas_hora(self):
        """Productividad: cantidad ÷ horas reales. Vacía en operaciones con tiempo por pedido."""
        if not self.min_real or self.operacion_detallada.es_por_pedido:
            return None
        return round(self.cantidad * 60 / self.min_real)
    # ----- Por operación (lista de trabajo) -----
    @property
    def hechas(self):
        """Piezas que lleva la tarea. Con ✓ es igual a la cantidad."""
        return self.cantidad if self.hecho else min(self.piezas_hechas, self.cantidad)

    @property
    def faltan(self):
        """Cantidad menos hechas, nunca menor que cero."""
        return max(self.cantidad - self.hechas, 0)
    
    @property
    def fecha_salida(self):
        if self.pedido and self.pedido.fecha_salida:
            return self.pedido.fecha_salida
        return None

    @property
    def alerta(self):
        fecha_obj = self.fecha_salida
        if not fecha_obj:
            return {
                "texto": "SIN FECHA",
                "clase": "status-neutral",
                "dias": None,
            }
        hoy = timezone.localdate()
        dias = (fecha_obj - hoy).days
        if dias < 0:
            return {
                "texto": f"ATRASADO ({abs(dias)}d)",
                "clase": "status-detenido",  # Rojo según app.css de INAHER
                "dias": dias,
            }
        elif dias == 0:
            return {
                "texto": "SALE HOY",
                "clase": "status-proceso",   # Ámbar / Alerta
                "dias": 0,
            }
        elif dias <= 2:
            return {
                "texto": f"URGENTE ({dias}d)",
                "clase": "status-proceso",   # Amarillo / Naranja
                "dias": dias,
            }
        else:
            return {
                "texto": "EN TIEMPO",
                "clase": "status-terminado", # Verde éxito
                "dias": dias,
            }
