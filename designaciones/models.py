from datetime import date
import re
from decimal import ROUND_HALF_UP, Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F
from django.utils import timezone
from pedidos.models import PartidaPedido, Pedido

def redondear(valor):
    """
    Como ROUND() de la hoja: el medio minuto sube (40.5 → 41).
    round() de Python redondea al par (40.5 → 40), por eso no se usa.
    """
    return int(Decimal(str(valor)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# Operación del catálogo para tareas temporales (regla 6): el tiempo vive en la tarea
TAREA_ESPECIAL = ("Tarea especial", "Tarea especial (ver Detalle)")
MAQUINA_MANUAL = "Tarea manual"
MATERIALES = ("fierro-galv", "inox-304")


def material_de_texto(texto):
    """inox si el texto lo dice (inox, acero 304/316); si no, fierro-galv. Igual que el motor de rutas."""
    t = (texto or "").lower()
    if re.search(r"inox|acero 30[46]|t-?30[46]|ss ?30[46]", t):
        return "inox-304"
    return "fierro-galv"


def material_de_operacion(nombre):
    """fierro-galv o inox-304 si el nombre de la operación lo trae; si no, None (operación sin material)."""
    for material in MATERIALES:
        if material in (nombre or ""):
            return material
    return None


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

    @property
    def tipos(self):
        """Tipos de máquina (o máquinas concretas) en orden de preferencia: "Torno CNC / Torno convencional"."""
        return [t.strip() for t in (self.tipo_maquina or "").split("/") if t.strip()]

    def opciones_maquina(self, maquinas=None):
        """
        Máquinas válidas para esta operación, en orden de preferencia (regla 3).
        Un token puede ser una máquina concreta o un tipo. Sin tipos capturados: todas las activas.
        """
        maquinas = list(maquinas if maquinas is not None else Maquina.objects.filter(activa=True))
        tipos = self.tipos
        if not tipos:
            return maquinas
        por_nombre = {m.nombre.lower(): m for m in maquinas}
        opciones = []
        for token in tipos:
            clave = token.lower()
            candidatas = [por_nombre[clave]] if clave in por_nombre else [m for m in maquinas if m.tipo.strip().lower() == clave]
            for m in candidatas:
                if m not in opciones:
                    opciones.append(m)
        return opciones

    def maquina_sola(self, maquinas=None):
        """La primera preferencia si es una máquina concreta o un tipo con una sola máquina; si no, None."""
        tipos = self.tipos
        maquinas = list(maquinas if maquinas is not None else Maquina.objects.filter(activa=True))
        if not tipos:
            return maquinas[0] if len(maquinas) == 1 else None
        primero = tipos[0].lower()
        concreta = [m for m in maquinas if m.nombre.lower() == primero]
        if concreta:
            return concreta[0]
        del_tipo = [m for m in maquinas if m.tipo.strip().lower() == primero]
        return del_tipo[0] if len(del_tipo) == 1 else None


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
    # 4 decimales: el min/pz se usa completo, sin recortarle decimales (2.025, no 2.03), como la hoja
    minutos_estandar = models.DecimalField(
        max_digits=10,
        decimal_places=4,
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
            return redondear(fijo.minutos if fijo.por_pedido else fijo.minutos * cantidad)
        for escalon in self.escalones.all():  # ordenados por "hasta"; el último sin tope = "más de"
            if escalon.hasta is None or cantidad <= escalon.hasta:
                return redondear(escalon.minutos)
        return None

    def minutos_para(self, cantidad):
        """Normal: min/pz del estudio × cantidad. Sin tiempo: 0."""
        fijos = self.minutos_fijos(cantidad)
        return fijos if fijos is not None else redondear(self.minutos_estandar * cantidad)

    @property
    def es_tarea_especial(self):
        return (self.madre.nombre, self.nombre) == TAREA_ESPECIAL

    @property
    def sin_tiempo(self):
        """Ni estudio, ni tiempo fijo, ni escalones: se muestra una raya y suma cero."""
        return (not self.minutos_estandar and not getattr(self, "tiempo_fijo", None)
                and not self.escalones.all() and not self.es_tarea_especial)

    @property
    def material(self):
        return material_de_operacion(self.nombre)

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
        null=True,
        blank=True,
        related_name="items_designados",
        verbose_name="Quién",
        help_text="Vacío = sin asignar: la tarea existe pero sus minutos no cuentan en ninguna persona.",
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
    # Hechas que ya traía al último Nuevo día: Min de hoy = min/pz × (Cant − esto)
    piezas_base = models.PositiveIntegerField(default=0, verbose_name="Hechas al iniciar el día")
    # Hechas que tenía antes de palomear: al quitar la ✓ regresa a este valor (regla 4)
    piezas_antes_check = models.PositiveIntegerField(default=0, verbose_name="Hechas antes de la ✓")
    cantidad_manual = models.BooleanField(
        default=False, verbose_name="Cant cambiada a mano",
        help_text="Si se cambió aquí, ya no sigue a la cantidad de la partida.",
    )
    min_estimado_pz = models.DecimalField(
        max_digits=7, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.01"))],
        verbose_name="Min estimado por pieza",
        help_text="Solo Tarea especial: Min = esto × Cant.",
    )
    minutos = models.PositiveIntegerField(
        default=0,
        verbose_name="Minutos estimados",
    )
    min_restantes = models.PositiveIntegerField(default=0, verbose_name="Min restantes")
    hecho = models.BooleanField(
        default=False,
        verbose_name="Completado (✓)",
    )
    hecho_en = models.DateTimeField(null=True, blank=True, verbose_name="✓ puesta el")
    hecho_por = models.CharField(max_length=150, blank=True, default="", verbose_name="✓ puesta por")
    hechas_en = models.DateTimeField(null=True, blank=True, verbose_name="Hechas capturadas el")
    hechas_por = models.CharField(max_length=150, blank=True, default="", verbose_name="Hechas capturadas por")

    class Cierre(models.TextChoices):
        CHECK = "CHECK", "✓"
        AVANCE = "AVANCE", "Avance"

    cierre = models.CharField(
        max_length=10, choices=Cierre.choices, blank=True, default="",
        verbose_name="Cómo se cerró en Nuevo día",
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
        permissions = [
            ("editar_designacion", "Puede cargar rutas, agregar, editar, asignar y quitar tareas"),
            ("palomear_designacion", "Puede poner ✓ y Hechas en Designación"),
            ("cerrar_dia", "Puede cerrar el día (Nuevo día)"),
            ("imprimir_designacion", "Puede imprimir y exportar Designación"),
        ]

    def __str__(self):
        quien = self.quien.nombre if self.quien_id else "Sin asignar"
        return f"{quien} - Paso {self.paso} ({self.operacion_detallada.nombre})"

    # ----- Reglas 2 y 4: Min, Hechas, Faltan, Min restantes -----
    @property
    def es_activa(self):
        """Activa = sigue en Designación (no archivada por Nuevo día ni por archivar el pedido)."""
        return not self.fecha_cierre and not self.cerrada_al_archivar

    @property
    def es_especial(self):
        return self.operacion_detallada.es_tarea_especial

    @property
    def es_por_pedido(self):
        return self.operacion_detallada.es_por_pedido

    @property
    def lleva_hechas(self):
        """Empaquetar y Contar y revisar (por pedido), tarea especial y tareas sin cantidad: solo ✓."""
        return bool(self.cantidad) and not self.es_por_pedido and not self.es_especial

    @property
    def sin_tiempo(self):
        """Raya en Min: la operación no tiene tiempo y la tarea suma cero (sale en Faltan de medir)."""
        return self.operacion_detallada.sin_tiempo and not self.min_estimado_pz and not self.minutos

    def _min_por_pieza(self):
        if self.es_especial:
            return self.min_estimado_pz or Decimal(0)
        return self.operacion_detallada.minutos_estandar or Decimal(0)

    def calcular_minutos(self):
        """
        Regla 2. Por pedido (tiempo fijo o escalones): sin multiplicar.
        Normal: min/pz × piezas, piezas = Cant − hechas al último Nuevo día.
        Tarea especial: min estimado × Cant (sin piezas: 1).
        """
        piezas = max(self.cantidad - self.piezas_base, 0)
        if self.es_especial:
            return redondear(self._min_por_pieza() * (self.cantidad or 1))
        fijos = self.operacion_detallada.minutos_fijos(self.cantidad)
        if fijos is not None:
            return fijos
        return redondear(self._min_por_pieza() * piezas)

    def calcular_restantes(self):
        """min/pz × Faltan, redondeado. Con ✓: 0. Sin avance desde el último Nuevo día: igual a Min."""
        if self.hecho:
            return 0
        if not self.lleva_hechas or self.piezas_hechas <= self.piezas_base:
            return self.minutos
        return min(redondear(self._min_por_pieza() * self.faltan), self.minutos)

    def save(self, *args, **kwargs):
        # Min se recalcula solo en las tareas activas; lo archivado no cambia (regla 2)
        if kwargs.get("update_fields") is None and self.operacion_detallada_id and self.es_activa:
            self.minutos = self.calcular_minutos()
        if self.es_activa:
            self.min_restantes = self.calcular_restantes()
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = list({*kwargs["update_fields"], "min_restantes"})
        super().save(*args, **kwargs)

    def poner_check(self, valor, quien=""):
        """✓ y Hechas van juntas: palomear pone Hechas = Cant; quitarla regresa Hechas a lo que tenía."""
        if valor == self.hecho:
            return
        ahora = timezone.now()
        if valor:
            self.piezas_antes_check = self.piezas_hechas
            self.piezas_hechas = self.cantidad
        else:
            self.piezas_hechas = min(self.piezas_antes_check, self.cantidad)
        self.hecho = valor
        self.hecho_en, self.hecho_por = (ahora, quien) if valor else (None, "")
        self.save(update_fields=["hecho", "piezas_hechas", "piezas_antes_check", "hecho_en", "hecho_por"])

    def poner_hechas(self, valor, quien=""):
        """Hechas al total pone la ✓ sola; si baja, la ✓ se quita. Guarda cuándo y quién."""
        valor = max(0, min(int(valor), self.cantidad))
        self.piezas_hechas = valor
        self.hechas_en, self.hechas_por = timezone.now(), quien
        completa = bool(self.cantidad) and valor >= self.cantidad
        if completa and not self.hecho:
            self.hecho, self.hecho_en, self.hecho_por = True, self.hechas_en, quien
            self.piezas_antes_check = valor
        elif not completa and self.hecho:
            self.hecho, self.hecho_en, self.hecho_por = False, None, ""
        self.save(update_fields=["piezas_hechas", "hecho", "hecho_en", "hecho_por",
                                 "hechas_en", "hechas_por", "piezas_antes_check"])

    @property
    def hechas_hoy(self):
        """Piezas hechas desde el último Nuevo día."""
        return max(self.hechas - self.piezas_base, 0)

    @property
    def min_hechos_hoy(self):
        """Min − Min restantes. Con ✓: igual a Min."""
        return max(self.minutos - self.min_restantes, 0)

    @property
    def piezas_dia(self):
        """En el Archivo: piezas de ese día (el renglón ya cerrado)."""
        return self.hechas_hoy if self.lleva_hechas else self.cantidad

    @property
    def tiene_avance(self):
        return not self.hecho and self.lleva_hechas and self.piezas_hechas > self.piezas_base

    @property
    def material_partida(self):
        return material_de_texto(self.partida.descripcion) if self.partida_id else None

    @property
    def aviso_material(self):
        """Naranja en operación: el material de la operación no es el de la partida (no aplica sin pedido)."""
        if not self.partida_id:
            return None
        op = self.operacion_detallada.material
        partida = self.material_partida
        if op and partida and op != partida:
            return f"La operación es {op} y la partida es {partida}"
        return None

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
        """Piezas que lleva la tarea (acumuladas). Con ✓ es igual a la cantidad."""
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
