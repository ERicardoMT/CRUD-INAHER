from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone


# Al archivar un día, las tareas pendientes se copian a la jornada siguiente y la
# original queda sin ✓ en la jornada cerrada. Para no contarlas doble, solo son
# "vigentes" las tareas hechas o las que están en jornadas abiertas.
Q_ITEM_VIGENTE = Q(hecho=True) | Q(designacion__cerrada=False)
Q_ITEM_VIGENTE_REL = Q(items_designacion__hecho=True) | Q(items_designacion__designacion__cerrada=False)
Q_ITEM_PENDIENTE_REL = Q(items_designacion__hecho=False, items_designacion__designacion__cerrada=False)


def porcentaje(parte, total):
    return round(parte * 100 / total) if total else 0


class Cliente(models.Model):
    nombre = models.CharField(max_length=150, unique=True, verbose_name="Nombre")

    class Meta:
        ordering = ["nombre"]
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"

    def __str__(self):
        return self.nombre


class PedidoQuerySet(models.QuerySet):

    def numero(self, numero):
        """El # del SAE acepta letras y números sin distinguir mayúsculas."""
        return self.filter(numero__iexact=(numero or "").strip())

    def activos(self):
        """Activos = EN ESPERA + EN PROCESO + TERMINADO (todo lo que no se ha entregado)."""
        return self.exclude(estado=Pedido.Estado.ENTREGADO)

    def por_filtro(self, clave):
        """Filtros de las tarjetas y del selector "Mostrar" del listado."""
        hoy = timezone.localdate()
        sin_terminar = self.activos().exclude(estado=Pedido.Estado.TERMINADO)
        filtros = {
            "activos": lambda: self.activos(),
            "atrasados": lambda: sin_terminar.filter(fecha_salida__lt=hoy),
            "sale_hoy": lambda: sin_terminar.filter(fecha_salida=hoy),
            "detenidos": lambda: self.activos().filter(detenido=True),
            "terminados": lambda: self.filter(estado=Pedido.Estado.TERMINADO),
            "entregados": lambda: self.filter(estado=Pedido.Estado.ENTREGADO),
            "todos": lambda: self.all(),
        }
        return filtros.get(clave, filtros["activos"])()

    def con_minutos(self):
        """Min total / Min restante de la ruta cargada en Designación."""
        return self.annotate(
            min_total=Coalesce(Sum("items_designacion__minutos", filter=Q_ITEM_VIGENTE_REL), 0),
            min_restante=Coalesce(Sum("items_designacion__minutos", filter=Q_ITEM_PENDIENTE_REL), 0),
        )


class Pedido(models.Model):

    class Estado(models.TextChoices):
        EN_ESPERA = "EN_ESPERA", "En espera"
        EN_PROCESO = "EN_PROCESO", "En proceso"
        TERMINADO = "TERMINADO", "Terminado"
        ENTREGADO = "ENTREGADO", "Entregado"

    # Estados a los que ya no se les asignan tareas en la designación
    ESTADOS_CERRADOS = [Estado.TERMINADO, Estado.ENTREGADO]

    ESTATUS_CLASE = {
        Estado.EN_ESPERA: "status-waiting",
        Estado.EN_PROCESO: "status-progress",
        Estado.TERMINADO: "status-finished",
        Estado.ENTREGADO: "status-finished",
    }

    numero = models.CharField(
        max_length=30,
        unique=True,
        verbose_name="Número de pedido",
    )

    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pedidos",
        verbose_name="Cliente",
    )

    # Resumen de las partidas (se llena solo con actualizar_resumen).
    # Lo usan Designación y el motor de rutas: "4 REBO 400 y 6 SCN-90 inox".
    descripcion = models.TextField(
        blank=True,
        editable=False,
        verbose_name="Descripción",
    )

    cantidad = models.PositiveIntegerField(
        default=0,
        editable=False,
        verbose_name="Cantidad total",
    )

    fecha_captura = models.DateField(
        default=timezone.localdate,
        verbose_name="Fecha de captura",
    )

    fecha_salida = models.DateField(
        verbose_name="Fecha de salida",
        blank=True,
        null=True,
    )

    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.EN_ESPERA,
        verbose_name="Estatus",
    )

    detenido = models.BooleanField(
        default=False,
        verbose_name="Detenido",
    )

    detenido_por = models.CharField(
        max_length=150,
        blank=True,
        default="",
        verbose_name="Detenido por",
        help_text="Material faltante · fecha esperada",
    )

    notas = models.TextField(
        blank=True,
        verbose_name="Notas",
    )

    fecha_creacion = models.DateTimeField(
        auto_now_add=True,
    )

    fecha_actualizacion = models.DateTimeField(
        auto_now=True,
    )

    objects = PedidoQuerySet.as_manager()

    class Meta:
        ordering = ["-fecha_creacion"]
        verbose_name = "Pedido"
        verbose_name_plural = "Pedidos"

    def __str__(self):
        return f"Pedido {self.numero}"

    @property
    def esta_cerrado(self):
        return self.estado in self.ESTADOS_CERRADOS

    @property
    def estatus_clase(self):
        return self.ESTATUS_CLASE.get(self.estado, "status-waiting")

    @property
    def dias_restantes(self):
        """Días = Fecha salida - HOY(). Solo para pedidos activos no terminados."""
        if not self.fecha_salida or self.esta_cerrado:
            return None
        return (self.fecha_salida - timezone.localdate()).days

    @property
    def alerta_estado(self):
        """Estado por fecha (se llena solo)."""
        if self.estado == self.Estado.ENTREGADO:
            return {"texto": "ENTREGADO", "clase": "status-terminado"}
        if self.estado == self.Estado.TERMINADO:
            return {"texto": "LISTO", "clase": "status-terminado"}

        dias = self.dias_restantes
        if dias is None:
            return {"texto": "SIN FECHA", "clase": "status-neutral"}
        if dias < 0:
            return {"texto": "ATRASADO", "clase": "status-detenido"}
        if dias == 0:
            return {"texto": "SALE HOY", "clase": "status-proceso"}
        if dias <= 2:
            return {"texto": "URGENTE", "clase": "status-proceso"}
        return {"texto": "EN TIEMPO", "clase": "status-terminado"}

    # ----- Avance (requiere .con_minutos() en el queryset) -----
    @property
    def min_hechos(self):
        return self.min_total - self.min_restante

    @property
    def pct_avance(self):
        return porcentaje(self.min_hechos, self.min_total)

    def actualizar_resumen(self):
        """Recalcula cantidad y descripción a partir de las partidas."""
        partidas = list(self.partidas.all())
        self.cantidad = sum(p.cantidad for p in partidas)
        if len(partidas) == 1:
            self.descripcion = partidas[0].descripcion
        else:
            self.descripcion = " y ".join(f"{p.cantidad} {p.descripcion}" for p in partidas)
        self.save(update_fields=["cantidad", "descripcion", "fecha_actualizacion"])

    def sincronizar_estatus(self):
        """
        Estatus automático con las ✓ de la designación:
        EN ESPERA → EN PROCESO con la primera ✓; → TERMINADO cuando todas tienen ✓;
        si se quita una ✓ a un TERMINADO regresa a EN PROCESO. ENTREGADO no se toca.
        """
        if self.estado == self.Estado.ENTREGADO:
            return
        tareas = self.items_designacion.filter(Q_ITEM_VIGENTE)
        hechas = tareas.filter(hecho=True).count()
        total = tareas.count()

        if total and hechas == total:
            nuevo = self.Estado.TERMINADO
        elif hechas:
            nuevo = self.Estado.EN_PROCESO
        elif self.estado == self.Estado.TERMINADO:
            nuevo = self.Estado.EN_PROCESO
        else:
            return

        if nuevo != self.estado:
            self.estado = nuevo
            self.save(update_fields=["estado", "fecha_actualizacion"])


class PartidaPedido(models.Model):
    pedido = models.ForeignKey(
        Pedido,
        on_delete=models.CASCADE,
        related_name="partidas",
    )
    cantidad = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1, "La cantidad debe ser mayor a 0.")],
        verbose_name="Cant",
    )
    descripcion = models.CharField(
        max_length=255,
        verbose_name="Descripción",
    )

    class Meta:
        ordering = ["id"]
        verbose_name = "Partida"
        verbose_name_plural = "Partidas"

    def __str__(self):
        return f"{self.cantidad} {self.descripcion}"
