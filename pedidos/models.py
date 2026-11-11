from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from urllib.parse import quote
from .catalogo import modelos_catalogo
import re
import unicodedata


# Al archivar un día, las tareas pendientes se copian a la jornada siguiente y la
# original queda sin ✓ en la jornada cerrada. Para no contarlas doble, solo son
# "vigentes" las tareas hechas o las que están en jornadas abiertas.
Q_ITEM_VIGENTE = Q(hecho=True) | Q(designacion__cerrada=False)
Q_ITEM_VIGENTE_REL = Q(items_designacion__hecho=True) | Q(items_designacion__designacion__cerrada=False)
Q_ITEM_PENDIENTE_REL = Q(items_designacion__hecho=False, items_designacion__designacion__cerrada=False)


def porcentaje(parte, total):
    return round(parte * 100 / total) if total else 0

# Letras (con acentos/ñ), números y signos comunes.
texto_seguro = RegexValidator(
    r"^[\w\s.,;:#°/()&'\"¿?¡!@%+\-]*$",
    "Solo letras, números y signos básicos (sin emojis ni símbolos especiales).",
)
solo_guia = RegexValidator(r"^[A-Za-z0-9\-]*$", "La guía solo lleva letras, números y guiones.")

ACUSE_MAX_MB = 5


def max_5mb(archivo):
    if archivo.size > ACUSE_MAX_MB * 1024 * 1024:
        raise ValidationError(f"El archivo pesa más de {ACUSE_MAX_MB} MB.")
solo_folio = RegexValidator(r"^[A-Za-z0-9\-]*$", "Solo letras, números y guiones.")


def normalizar(texto):
    """Para buscar: sin acentos, minúsculas, solo letras y números ("#F-2231" → "f2231")."""
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^0-9a-z]", "", texto.lower())

def detectar_modelo(descripcion):
    """Modelo exacto según el catálogo del motor de rutas. R-3 no trae MR-338 ni NR-3."""
    texto = (descripcion or "").upper()
    for modelo in sorted(modelos_catalogo(), key=len, reverse=True):
        partes = [re.escape(p) for p in re.split(r"[\s\-]+", modelo.upper()) if p]
        patron = r"(?<![A-Z0-9])" + r"[\s\-]?".join(partes) + r"(?![A-Z0-9])"
        if re.search(patron, texto):
            return modelo
    return ""


def armar_busqueda(pedido):
    """Texto del buscador: # pedido, cotización, OC, cliente, folio, partidas, modelos y guías."""
    piezas = [pedido.numero, pedido.cotizacion, pedido.oc_cliente, pedido.factura_folio,
              pedido.cliente.nombre if pedido.cliente_id else ""]
    for descripcion, modelo in pedido.partidas.values_list("descripcion", "modelo"):
        piezas += [descripcion, modelo]
    piezas += list(pedido.entregas.values_list("guia", flat=True))
    return "|".join(normalizar(p) for p in piezas if p)

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

    def entregados_cobrables(self):
        """Entregados que cuentan para cobranza (los "No se terminó" no cuentan)."""
        return self.filter(estado=Pedido.Estado.ENTREGADO, archivado_sin_terminar=False)

    def sin_facturar(self):
        return self.entregados_cobrables().filter(factura_estado=Pedido.Factura.PENDIENTE)

    def sin_pagar(self):
        return (
            self.entregados_cobrables()
            .exclude(factura_estado=Pedido.Factura.PENDIENTE)
            .exclude(pagos__tipo=Pago.Tipo.LIQUIDACION)
        )

    

    def buscar(self, texto):
        clave = normalizar(texto)
        return self.filter(busqueda__contains=clave) if clave else self
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
    class MotivoNoTerminado(models.TextChoices):
        CANCELADO = "CANCELADO", "Cancelado por el cliente"
        ERROR_CAPTURA = "ERROR_CAPTURA", "Error de captura / duplicado"
        STOCK = "STOCK", "Se surtió de stock"
        OTRO = "OTRO", "Otro"

    class Factura(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        FACTURADO = "FACTURADO", "Facturado"
        NO_PIDIO = "NO_PIDIO", "No pidió factura"


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
        db_index=True,
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
        db_index=True,
    )

    archivado_sin_terminar = models.BooleanField(
        default=False,
        verbose_name="Archivado sin terminar",
        help_text="Se archivó con tareas sin ✓ o sin estar terminado (p. ej. cancelado por el cliente).",
    )

    archivado_motivo = models.CharField(
        max_length=20, choices=MotivoNoTerminado.choices, blank=True, default="",
        verbose_name="Motivo (no se terminó)",
    )
    archivado_motivo_otro = models.CharField(
        max_length=120, blank=True, default="", validators=[texto_seguro], verbose_name="Otro motivo",
    )

    cotizacion = models.CharField(
        max_length=30, blank=True, default="", db_index=True, validators=[texto_seguro],
        verbose_name="Cotización (SAE)",
    )
    oc_cliente = models.CharField(
        max_length=40, blank=True, default="", db_index=True, validators=[texto_seguro],
        verbose_name="OC del cliente",
    )

    factura_estado = models.CharField(
        max_length=10, choices=Factura.choices, default=Factura.PENDIENTE, db_index=True, verbose_name="Facturado",
    )
    factura_fecha = models.DateField(null=True, blank=True, verbose_name="Fecha de factura")
    factura_folio = models.CharField(
        max_length=30, blank=True, default="", db_index=True, validators=[solo_folio], verbose_name="Folio",
    )
    factura_nota = models.CharField(max_length=200, blank=True, default="", validators=[texto_seguro], verbose_name="Nota de factura")
    factura_por = models.CharField(max_length=150, blank=True, default="", verbose_name="Facturó")

    busqueda = models.TextField(blank=True, default="", editable=False)

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
        self.actualizar_busqueda()

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
        self.actualizar_busqueda()
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

    def actualizar_busqueda(self):
        self.busqueda = armar_busqueda(self)
        Pedido.objects.filter(pk=self.pk).update(busqueda=self.busqueda)

    @property
    def envio_resumen(self):
        """ENVIADO: última guía y cuántas entregas más hay (+N)."""
        entregas = list(self.entregas.all())
        if not entregas:
            return None
        ultima = entregas[-1]
        guia = f"…{ultima.guia[-4:]}" if ultima.guia else ""
        return {
            "texto": " ".join(filter(None, [ultima.paqueteria_nombre, guia])) or f"{ultima.cantidad} pzas",
            "extra": len(entregas) - 1,
            "completo": self.estado == self.Estado.ENTREGADO,
        }

    @property
    def dias_sin_facturar(self):
        if self.factura_estado != self.Factura.PENDIENTE or not self.fecha_entrega or self.archivado_sin_terminar:
            return None
        return (timezone.localdate() - self.fecha_entrega).days

    @property
    def liquidacion(self):
        """El pago de liquidación, o None si todavía no se liquida."""
        return next((p for p in self.pagos.all() if p.tipo == Pago.Tipo.LIQUIDACION), None)

    @property
    def dias_sin_pagar(self):
        """Desde la factura o, si no pidió factura, desde la entrega."""
        if self.archivado_sin_terminar or self.factura_estado == self.Factura.PENDIENTE or self.liquidacion:
            return None
        desde = self.factura_fecha or self.fecha_entrega
        return (timezone.localdate() - desde).days if desde else None   

    @property
    def situacion_archivo(self):
        if self.archivado_sin_terminar:
            motivo = self.archivado_motivo_otro or self.get_archivado_motivo_display() or "sin motivo"
            return f"No se terminó · {motivo}"
        return "Terminado" if self.archivado else "Sin archivar"

    @property
    def factura_texto(self):
        if self.factura_estado == self.Factura.FACTURADO:
            return self.factura_folio
        if self.factura_estado == self.Factura.NO_PIDIO:
            return "No pidió factura"
        dias = self.dias_sin_facturar
        return f"Pendiente · {dias} días" if dias is not None else "—"

    @property
    def pago_texto(self):
        if self.liquidacion:
            return f"Pagado {self.liquidacion.fecha:%d/%m/%Y}"
        pagos = len(self.pagos.all())
        return f"Parcial · {pagos} pago(s)" if pagos else "Pendiente"

    def archivar(self, no_terminado=False, motivo="", motivo_otro=""):
        """
        Manda el pedido al Archivo. Sus tareas pendientes salen de Designación:
        Ya se terminó → se cierran como "✓ al archivar"; No se terminó → quedan apartadas (no se borran).
        """
        pendientes = self.items_designacion.filter(hecho=False, designacion__cerrada=False)
        if no_terminado:
            pendientes.update(cerrada_al_archivar=True)
        else:
            pendientes.update(cerrada_al_archivar=True, hecho=True, fecha_cierre=timezone.localdate())
        self.archivado = True
        self.archivado_en = timezone.now()
        self.archivado_sin_terminar = no_terminado
        self.archivado_motivo = motivo
        self.archivado_motivo_otro = motivo_otro
        self.save(update_fields=[
            "archivado", "archivado_en", "archivado_sin_terminar",
            "archivado_motivo", "archivado_motivo_otro", "fecha_actualizacion",
        ])

    def desarchivar(self):
        """Regresa a Activos. Las tareas cerradas "al archivar" vuelven pendientes a la jornada abierta."""
        from designaciones.models import DesignacionDia  # import local: designaciones importa pedidos

        tareas = self.items_designacion.filter(cerrada_al_archivar=True)
        if tareas.exists():
            jornada = (
                DesignacionDia.objects.filter(cerrada=False).order_by("-fecha").first()
                or DesignacionDia.objects.get_or_create(fecha=timezone.localdate())[0]
            )
            tareas.update(designacion=jornada, hecho=False, cerrada_al_archivar=False, fecha_cierre=None)
        self.archivado = False
        self.archivado_en = None
        self.archivado_sin_terminar = False
        self.archivado_motivo = ""
        self.archivado_motivo_otro = ""
        self.save(update_fields=[
            "archivado", "archivado_en", "archivado_sin_terminar",
            "archivado_motivo", "archivado_motivo_otro", "fecha_actualizacion",
        ])

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
    modelo = models.CharField(
        max_length=40, blank=True, 
        default="", 
        db_index=True, 
        editable=False, 
        verbose_name="Modelo"
    )
    class Meta:
        ordering = ["id"]
        verbose_name = "Partida"
        verbose_name_plural = "Partidas"

    def __str__(self):
        return f"{self.cantidad} {self.descripcion}"
    
    def save(self, *args, **kwargs):
        self.modelo = detectar_modelo(self.descripcion)
        super().save(*args, **kwargs)

    @property
    def entregado(self):
        return sum(e.cantidad for e in self.entregas.all())

    @property
    def faltan(self):
        return max(self.cantidad - self.entregado, 0)

class MovimientoPedido(models.Model):
    """Bitácora: quién eliminó, archivó o desarchivó un pedido."""
    class Accion(models.TextChoices):
        ELIMINADO = "ELIMINADO", "Eliminado"
        ARCHIVADO = "ARCHIVADO", "Archivado"
        ARCHIVADO_SIN_TERMINAR = "ARCHIVADO_SIN_TERMINAR", "Archivado sin terminar"
        DESARCHIVADO = "DESARCHIVADO", "Desarchivado"
        FOLIO_CAMBIADO = "FOLIO_CAMBIADO", "Folio de factura cambiado"

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

    class Paqueteria(models.TextChoices):
        ESTAFETA = "ESTAFETA", "Estafeta"
        DHL = "DHL", "DHL"
        FEDEX = "FEDEX", "FedEx"
        PAQUETEXPRESS = "PAQUETEXPRESS", "Paquetexpress"
        CASTORES = "CASTORES", "Castores"
        TRES_GUERRAS = "TRES_GUERRAS", "Tres Guerras"
        FLETE_PROPIO = "FLETE_PROPIO", "Flete propio"
        CLIENTE_RECOGE = "CLIENTE_RECOGE", "Cliente recoge"
        OTRA = "OTRA", "Otra"

    SIN_GUIA = {Paqueteria.FLETE_PROPIO, Paqueteria.CLIENTE_RECOGE}
    RASTREO = {
        Paqueteria.ESTAFETA: "https://rastreositecorecms.azurewebsites.net/Tracking/searchByGet/?wayBillType=1&wayBill={}",
        Paqueteria.DHL: "https://www.dhl.com/mx-es/home/rastreo.html?tracking-id={}&submit=1",
        Paqueteria.FEDEX: "https://www.fedex.com/fedextrack/?trknbr={}",
        Paqueteria.PAQUETEXPRESS: "https://www.paquetexpress.com.mx/rastreo/{}",
    }

    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="entregas")
    fecha = models.DateField(default=timezone.localdate, verbose_name="Fecha de entrega")
    cantidad = models.PositiveIntegerField(
        validators=[MinValueValidator(1, "La cantidad debe ser mayor a 0.")],
        verbose_name="Cantidad entregada",
    )
    nota = models.CharField(max_length=200, blank=True, default="", validators=[texto_seguro], verbose_name="Nota")
    recibe = models.CharField(max_length=80, blank=True, default="", validators=[texto_seguro], verbose_name="Quién recibe")
    paqueteria = models.CharField(max_length=20, choices=Paqueteria.choices, blank=True, default="", verbose_name="Paquetería")
    paqueteria_otra = models.CharField(max_length=60, blank=True, default="", validators=[texto_seguro], verbose_name="¿Cuál paquetería?")
    guia = models.CharField(max_length=40, blank=True, default="", validators=[solo_guia], verbose_name="Número de guía", db_index= True,)
    acuse = models.ImageField(
        upload_to="acuses/%Y/%m/", blank=True,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp"]), max_5mb],
        verbose_name="Foto / acuse",
    )
    registrada_por = models.CharField(max_length=150, blank=True, default="", verbose_name="Registró")
    registrada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["fecha", "id"]
        verbose_name = "Entrega"
        verbose_name_plural = "Entregas"

    def __str__(self):
        return f"{self.cantidad} pzas · {self.pedido.numero} · {self.fecha:%d/%m/%Y}"
    
    @property
    def paqueteria_nombre(self):
        """Nombre a mostrar: si es "Otra", lo que escribió el usuario."""
        if self.paqueteria == self.Paqueteria.OTRA and self.paqueteria_otra:
            return self.paqueteria_otra
        return self.get_paqueteria_display()
    
    @property
    def rastreo_url(self):
        plantilla = self.RASTREO.get(self.paqueteria)
        return plantilla.format(quote(self.guia)) if plantilla and self.guia else ""
class EntregaPartida(models.Model):
    """Cuánto de cada partida se fue en una entrega."""
    entrega = models.ForeignKey(Entrega, on_delete=models.CASCADE, related_name="partidas")
    partida = models.ForeignKey(PartidaPedido, on_delete=models.CASCADE, related_name="entregas")
    cantidad = models.PositiveIntegerField(verbose_name="Entregado")

    class Meta:
        verbose_name = "Partida entregada"
        verbose_name_plural = "Partidas entregadas"
class Pago(models.Model):
    """Pagos del pedido. Sin importes: la cobranza se lleva en el SAE."""

    class Tipo(models.TextChoices):
        ANTICIPO = "ANTICIPO", "Anticipo"
        ABONO = "ABONO", "Abono"
        LIQUIDACION = "LIQUIDACION", "Liquidación (pago total)"

    class Forma(models.TextChoices):
        TRANSFERENCIA = "TRANSFERENCIA", "Transferencia"
        EFECTIVO = "EFECTIVO", "Efectivo"
        TARJETA = "TARJETA", "Tarjeta"
        MERCADO_PAGO = "MERCADO_PAGO", "Mercado Pago"
        CREDITO = "CREDITO", "Crédito (por cobrar)"

    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="pagos")
    fecha = models.DateField(default=timezone.localdate, verbose_name="Fecha de pago")
    tipo = models.CharField(max_length=15, choices=Tipo.choices, default=Tipo.ANTICIPO, verbose_name="Tipo")
    forma = models.CharField(max_length=15, choices=Forma.choices, default=Forma.TRANSFERENCIA, verbose_name="Forma de pago")
    nota = models.CharField(max_length=200, blank=True, default="", validators=[texto_seguro], verbose_name="Nota")
    registrado_por = models.CharField(max_length=150, blank=True, default="", verbose_name="Registró")
    registrado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["fecha", "id"]
        verbose_name = "Pago"
        verbose_name_plural = "Pagos"

    def __str__(self):
        return f"{self.get_tipo_display()} · {self.pedido.numero} · {self.fecha:%d/%m/%Y}"
