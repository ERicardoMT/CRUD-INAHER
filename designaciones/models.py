from datetime import date
from django.db import models
from django.utils import timezone
from pedidos.models import PartidaPedido, Pedido


class Operario(models.Model):
    nombre = models.CharField(max_length=100, unique=True, verbose_name="Nombre")
    activo = models.BooleanField(default=True, verbose_name="Activo")
    orden = models.PositiveIntegerField(default=0, verbose_name="Orden de visualización")

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

    class Meta:
        ordering = ["nombre"]
        verbose_name = "Máquina"
        verbose_name_plural = "Máquinas"

    def __str__(self):
        return self.nombre


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
    minutos = models.PositiveIntegerField(
        default=0,
        verbose_name="Minutos estimados",
    )
    hecho = models.BooleanField(
        default=False,
        verbose_name="Completado (✓)",
    )
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
        # Cálculo automático de minutos si no se especificaron manualmente
        if not self.minutos and self.operacion_detallada and self.operacion_detallada.minutos_estandar:
            self.minutos = int(round(float(self.operacion_detallada.minutos_estandar) * self.cantidad))
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
