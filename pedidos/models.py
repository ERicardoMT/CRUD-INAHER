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

    def vigentes(self):
        """Todo lo que no se ha mandado al Histórico."""
        return self.filter(archivado=False)

    def activos(self):
        """Activos = EN ESPERA + EN PROCESO + TERMINADO (sin entregar y sin archivar)."""
        return self.vigentes().exclude(estado=Pedido.Estado.ENTREGADO)

    def carga_planta(self):
        """Pedidos a los que se les pueden asignar tareas en la designación."""
        return self.vigentes().exclude(estado__in=Pedido.ESTADOS_CERRADOS)

    def por_filtro(self, clave):
        """Filtros de las tarjetas y del selector "Mostrar" del listado."""
        hoy = timezone.localdate()
        sin_terminar = self.activos().exclude(estado=Pedido.Estado.TERMINADO)
        filtros = {
            "activos": lambda: self.activos(),
            "atrasados": lambda: sin_terminar.filter(fecha_salida__lt=hoy),
            "sale_hoy": lambda: sin_terminar.filter(fecha_salida=hoy),
            "detenidos": lambda: self.activos().filter(detenido=True),
            "terminados": lambda: self.vigentes().filter(estado=Pedido.Estado.TERMINADO),
            "entregados": lambda: self.vigentes().filter(estado=Pedido.Estado.ENTREGADO),
            "todos": lambda: self.vigentes(),
            "historico": lambda: self.filter(archivado=True),
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

    # Bandera puesta a mano: lo automático (tareas bloqueadas) nunca la apaga
    detenido_manual = models.BooleanField(
        default=False,
        verbose_name="Detenido a mano",
    )

    detenido_fecha_esperada = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha esperada",
        help_text="Cuándo se espera el material o la liberación.",
    )

    fecha_terminado = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de terminado",
    )

    fecha_entrega = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de entrega",
        help_text="Se llena al completar las entregas.",
    )

    notas = models.TextField(
        blank=True,
        verbose_name="Notas",
    )

    # ----- Histórico -----
    archivado = models.BooleanField(
        default=False,
        verbose_name="Archivado (Histórico)",
    )

    archivado_en = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de archivado",
    )

    archivado_sin_terminar = models.BooleanField(
        default=False,
        verbose_name="Archivado sin terminar",
        help_text="Se archivó con tareas sin ✓ o sin estar terminado (p. ej. cancelado por el cliente).",
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
            return {"texto": "URGENTE", "clase": "status-urgente"}
        return {"texto": "EN TIEMPO", "clase": "status-terminado"}

    # ----- Reglas de Archivar / Eliminar -----
    def tareas_sin_palomear(self):
        """Tareas vigentes de la designación que aún no tienen ✓."""
        return self.items_designacion.filter(hecho=False, designacion__cerrada=False).count()

    def tiene_avance(self):
        """¿Tiene al menos una ✓ en la designación?"""
        return self.items_designacion.filter(hecho=True).exists()

    def archivar_es_sin_terminar(self):
        """Archivar es "normal" solo si está TERMINADO/ENTREGADO y sin tareas pendientes."""
        return not self.esta_cerrado or self.tareas_sin_palomear() > 0

    # ----- Avance (requiere .con_minutos() en el queryset) -----
    @property
    def min_hechos(self):
        return self.min_total - self.min_restante

    @property
    def pct_avance(self):
        return porcentaje(self.min_hechos, self.min_total)

    def avance_partidas(self):
        """
        % por partida = minutos con ✓ ÷ minutos de todas sus tareas.
        Tareas sin partida (p. ej. Empaquetar, que cuenta una vez) solo suman al pedido.
        """
        datos = {
            fila["partida_id"]: fila
            for fila in self.items_designacion.filter(Q_ITEM_VIGENTE, partida__isnull=False)
            .values("partida_id")
            .annotate(total=Sum("minutos"), hechos=Sum("minutos", filter=Q(hecho=True)))
        }
        resultado = []
        for partida in self.partidas.all():
            fila = datos.get(partida.pk)
            total = (fila or {}).get("total") or 0
            hechos = (fila or {}).get("hechos") or 0
            resultado.append({
                "partida": partida,
                "min_total": total,
                "pct": porcentaje(hechos, total) if total else None,
            })
        return resultado

    def actualizar_resumen(self):
        """Recalcula cantidad y descripción a partir de las partidas."""
        partidas = list(self.partidas.all())
        self.cantidad = sum(p.cantidad for p in partidas)
        if len(partidas) == 1:
            self.descripcion = partidas[0].descripcion
        else:
            self.descripcion = " y ".join(f"{p.cantidad} {p.descripcion}" for p in partidas)
        self.save(update_fields=["cantidad", "descripcion", "fecha_actualizacion"])

    def establecer_estado(self, nuevo, guardar=True):
        """
        Único lugar donde cambia el estatus. TERMINADO guarda su fecha;
        si el pedido vuelve a producción, esa fecha se borra.
        """
        campos = ["estado", "fecha_terminado", "fecha_entrega", "fecha_actualizacion"]
        self.estado = nuevo
        if nuevo == self.Estado.TERMINADO:
            self.fecha_terminado = self.fecha_terminado or timezone.localdate()
        elif nuevo in (self.Estado.EN_ESPERA, self.Estado.EN_PROCESO):
            self.fecha_terminado = None
        if nuevo != self.Estado.ENTREGADO:
            self.fecha_entrega = None
        if guardar:
            self.save(update_fields=campos)

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
            self.establecer_estado(nuevo)

    def sincronizar_detenido(self):
        """
        DETENIDO automático: se enciende si una tarea pendiente del pedido está
        bloqueada por material y se apaga cuando ya no hay ninguna.
        Nunca toca una bandera puesta a mano.
        """
        if self.detenido_manual:
            return
        bloqueada = (
            self.items_designacion.filter(hecho=False, designacion__cerrada=False)
            .exclude(bloqueado_por="")
            .order_by("paso", "id")
            .first()
        )
        detenido = bloqueada is not None
        motivo = bloqueada.bloqueado_por if bloqueada else ""
        if (detenido, motivo) != (self.detenido, self.detenido_por):
            self.detenido = detenido
            self.detenido_por = motivo
            if not detenido:
                self.detenido_fecha_esperada = None
            self.save(update_fields=["detenido", "detenido_por", "detenido_fecha_esperada", "fecha_actualizacion"])

    # ----- Entregas -----
    @property
    def cantidad_entregada(self):
        return sum(e.cantidad for e in self.entregas.all())

    @property
    def cantidad_por_entregar(self):
        return max(self.cantidad - self.cantidad_entregada, 0)

    @property
    def entrega_parcial(self):
        """Hay entregas pero aún falta (el pedido sigue abierto: "entregado X de N")."""
        entregado = self.cantidad_entregada
        return 0 < entregado < self.cantidad

    def actualizar_por_entregas(self):
        """
        Completo → ENTREGADO con la fecha de la última entrega.
        Parcial → sigue abierto (EN ESPERA pasa a EN PROCESO).
        Si se borra una entrega de un ENTREGADO, regresa según sus ✓.
        """
        # .order_by() fuerza la consulta: ignora entregas precargadas que ya no estén al día
        entregas = list(self.entregas.order_by("fecha", "id"))
        total = sum(e.cantidad for e in entregas)
        if self.cantidad and total >= self.cantidad:
            self.establecer_estado(self.Estado.ENTREGADO, guardar=False)
            self.fecha_entrega = max(e.fecha for e in entregas)
            self.save(update_fields=["estado", "fecha_terminado", "fecha_entrega", "fecha_actualizacion"])
            return
        if self.estado == self.Estado.ENTREGADO:
            self.establecer_estado(self.Estado.EN_PROCESO)
            self.sincronizar_estatus()
        elif total and self.estado == self.Estado.EN_ESPERA:
            self.establecer_estado(self.Estado.EN_PROCESO)


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


class MovimientoPedido(models.Model):
    """Bitácora: quién eliminó, archivó o desarchivó un pedido."""

    class Accion(models.TextChoices):
        ELIMINADO = "ELIMINADO", "Eliminado"
        ARCHIVADO = "ARCHIVADO", "Archivado"
        ARCHIVADO_SIN_TERMINAR = "ARCHIVADO_SIN_TERMINAR", "Archivado sin terminar"
        DESARCHIVADO = "DESARCHIVADO", "Desarchivado"

    fecha = models.DateTimeField(auto_now_add=True, verbose_name="Fecha")
    accion = models.CharField(max_length=30, choices=Accion.choices, verbose_name="Acción")
    # Se guarda el número como texto para que el registro sobreviva a la eliminación
    pedido_numero = models.CharField(max_length=30, verbose_name="# Pedido")
    detalle = models.CharField(max_length=255, blank=True, default="", verbose_name="Detalle")
    usuario = models.CharField(max_length=150, verbose_name="Quién")

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "Movimiento de pedido"
        verbose_name_plural = "Bitácora de pedidos"

    def __str__(self):
        return f"{self.get_accion_display()} · {self.pedido_numero} · {self.usuario}"


class Entrega(models.Model):
    """Entrega a cliente. Admite parciales: el pedido se cierra al completar la cantidad."""
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="entregas")
    fecha = models.DateField(default=timezone.localdate, verbose_name="Fecha de entrega")
    cantidad = models.PositiveIntegerField(
        validators=[MinValueValidator(1, "La cantidad debe ser mayor a 0.")],
        verbose_name="Cantidad entregada",
    )
    nota = models.CharField(max_length=200, blank=True, default="", verbose_name="Nota")
    registrada_por = models.CharField(max_length=150, blank=True, default="", verbose_name="Registró")
    registrada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["fecha", "id"]
        verbose_name = "Entrega"
        verbose_name_plural = "Entregas"

    def __str__(self):
        return f"{self.cantidad} pzas · {self.pedido.numero} · {self.fecha:%d/%m/%Y}"
