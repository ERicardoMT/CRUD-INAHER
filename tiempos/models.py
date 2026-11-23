"""
Estudio de tiempos · versión 1.4. Una medición por renglón.
Lo que se calcula de cada medición vive aquí; lo que depende de las demás (alertas y mediana) en calculos.py.
"""
import re
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from designaciones.models import (
    MADRE_EMPAQUETAR, Maquina, OperacionDetallada, OperacionMadre, Operario, material_de_operacion, redondear,
)
from pedidos.models import max_5mb

VARIOS_MODELOS = "Varios modelos"
# Material que dice el nombre de la operación → letra del material de la medición (regla 3)
LETRA_MATERIAL = {"inox-304": "I", "fierro-galv": "F"}


def segundos_de(texto, acarrear=False):
    """
    'min:seg' → segundos. Minutos sin tope (74:11) y segundos de 00 a 59 (regla 1).
    acarrear=True, solo al importar la hoja: 0:80 entra como 1:20.
    """
    texto = str(texto or "").strip()
    if not texto:
        return None
    partes = re.fullmatch(r"(\d{1,4}):(\d{1,2})", texto)
    if not partes:
        raise ValidationError("Escribe el tiempo como min:seg, por ejemplo 1:19.")
    minutos, segundos = int(partes[1]), int(partes[2])
    if segundos > 59 and not acarrear:
        raise ValidationError("Los segundos van de 00 a 59.")
    return minutos * 60 + segundos


def texto_mmss(segundos):
    """Segundos → 'min:seg' (79 → '1:19')."""
    return f"{segundos // 60}:{segundos % 60:02d}" if segundos is not None else ""


def con_signo(numero):
    """Porcentaje entero con signo, como la hoja: +4 · 0 · −12."""
    if numero is None:
        return ""
    entero = redondear(numero)
    return f"{entero:+d}".replace("-", "−") if entero else "0"


def a_decimales(valor, lugares):
    """Como la hoja: el medio sube (redondeo medio hacia arriba)."""
    return Decimal(valor).quantize(Decimal(1).scaleb(-lugares), rounding=ROUND_HALF_UP)

class Importacion(models.Model):
    """Una carga del libro (12g): sirve para saber el origen y para deshacerla."""

    fecha = models.DateTimeField(auto_now_add=True, verbose_name="Cuándo")
    usuario = models.CharField(max_length=150, verbose_name="Quién")
    archivo = models.CharField(max_length=255, verbose_name="Archivo")
    cargadas = models.PositiveIntegerField(default=0, verbose_name="Mediciones cargadas")
    deshecha = models.BooleanField(default=False, verbose_name="Deshecha")

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "Importación del estudio"
        verbose_name_plural = "Importaciones del estudio"

    def __str__(self):
        return f"{self.archivo} · {timezone.localtime(self.fecha):%d/%m/%Y %H:%M}"


class MedicionBorrada(models.Model):
    """12g: lo que se borra en el sistema no regresa al volver a importar el libro."""

    clave = models.CharField(max_length=255, db_index=True)
    fecha = models.DateTimeField(auto_now_add=True)

class MedicionTiempo(models.Model):
    class Material(models.TextChoices):
        FIERRO = "F", "Fierro"
        INOX = "I", "Inox"
        AMBOS = "FI", "Fierro e inox"

    class Alerta(models.TextChoices):
        REVISAR = "REVISAR", "revisar"
        EXCLUIDA = "EXCLUIDA", "excluida"
    class Origen(models.TextChoices):
        SISTEMA = "SISTEMA", "Capturada en el sistema"
        IMPORTADA = "IMPORTADA", "Importada de la hoja"

    fecha = models.DateField(default=timezone.localdate, verbose_name="Fecha")
    quien_midio = models.CharField(max_length=80, blank=True, default="", verbose_name="Quién midió")
    operador = models.ForeignKey(
        Operario, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Operador"
    )
    modelo_pieza = models.CharField(max_length=150, blank=True, default="", verbose_name="Modelo")
    # Empaquetar (página 10): [{"modelo": "MKD-2", "piezas": 16}, ...]; la muestra es la suma
    modelos = models.JSONField(default=list, blank=True, verbose_name="Modelos empacados")
    operacion_madre = models.ForeignKey(
        OperacionMadre, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Operación madre"
    )
    operacion_detallada = models.ForeignKey(
        OperacionDetallada, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="mediciones", verbose_name="Operación detallada",
    )
    # Escrita a mano porque no está en el catálogo: queda NUEVA y no alimenta ningún tiempo (regla 3)
    detallada_nueva = models.CharField(max_length=200, blank=True, default="", verbose_name="Operación detallada (nueva)")
    maquina = models.ForeignKey(
        Maquina, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Máquina"
    )
    medida = models.CharField(max_length=50, blank=True, default="", verbose_name="Medida")
    material = models.CharField(max_length=2, choices=Material.choices, blank=True, default="", verbose_name="Material")

    tiempo_1_pieza = models.CharField(max_length=10, blank=True, default="", verbose_name="1 pieza (min:seg)")
    muestra_piezas = models.PositiveIntegerField(
        default=1, validators=[MinValueValidator(1, "Las piezas deben ser más de 0.")], verbose_name="Muestra (piezas)",
    )
    muestra_tiempo_total = models.CharField(max_length=10, verbose_name="Tiempo total (min:seg)")

    foto = models.ImageField(
        upload_to="estudio_tiempos/%Y/%m/", blank=True,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp"]), max_5mb], verbose_name="Foto",
    )
    foto_url = models.URLField(blank=True, default="", verbose_name="Liga de la foto")  # la que trae la hoja
    observaciones = models.TextField(blank=True, default="", verbose_name="Observaciones")
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    # Se calculan solos (regla 2) y al revisar su operación (regla 4)
    teorico = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True, verbose_name="Teórico (min)")
    pct_dif = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True, verbose_name="% dif.")
    min_pz = models.DecimalField(max_digits=9, decimal_places=2, default=0, verbose_name="Min/pz de la muestra")
    desvio = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True, verbose_name="Desvío")
    alerta = models.CharField(max_length=10, choices=Alerta.choices, blank=True, default="", verbose_name="Alerta")
    origen = models.CharField(max_length=10, choices=Origen.choices, default=Origen.SISTEMA, verbose_name="Origen")
    importacion = models.ForeignKey(
        Importacion, on_delete=models.SET_NULL, null=True, blank=True, related_name="mediciones", verbose_name="Importación",
    )
    fila_hoja = models.PositiveIntegerField(null=True, blank=True, verbose_name="Fila del libro")

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "Medición de tiempo"
        verbose_name_plural = "Mediciones de tiempos"
        permissions = [("administrar_estudio", "Puede capturar mediciones y aprobar tiempos")]

    def __str__(self):
        return f"{self.operacion_nombre} ({self.fecha:%d/%m/%Y})"

    # ----- la operación de la medición
    @property
    def es_empaquetar(self):
        return bool(self.operacion_madre_id) and self.operacion_madre.nombre == MADRE_EMPAQUETAR

    @property
    def es_nueva(self):
        return not self.operacion_detallada_id

    @property
    def operacion_nombre(self):
        return self.operacion_detallada.nombre if self.operacion_detallada_id else self.detallada_nueva

    @property
    def clave_operacion(self):
        """Las mediciones de la misma operación se revisan juntas (regla 4)."""
        if self.operacion_detallada_id:
            return ("catalogo", self.operacion_detallada_id)
        return ("nueva", self.operacion_madre_id, self.detallada_nueva.strip().lower())

    @property
    def material_esperado(self):
        """F o I si el nombre de la operación lo dice; None si no trae material."""
        return LETRA_MATERIAL.get(material_de_operacion(self.operacion_nombre))

    @property
    def material_contradice(self):
        """Naranja: operación inox-304 con Fierro, o fierro-galv con Inox. Fierro e inox nunca contradice."""
        esperado = self.material_esperado
        return bool(esperado) and self.material in (self.Material.FIERRO, self.Material.INOX) and self.material != esperado

    @property
    def excluida(self):
        return self.alerta == self.Alerta.EXCLUIDA

    # ----- lo que se calcula solo (regla 2)
    def calcular(self):
        """Teórico a 1 decimal; % dif. contra el teórico ya redondeado; min/pz a 2 decimales."""
        total = Decimal(segundos_de(self.muestra_tiempo_total) or 0) / 60
        piezas = self.muestra_piezas or 1
        self.min_pz = a_decimales(total if self.es_empaquetar else total / piezas, 2)  # Empaquetar: por pedido
        uno = None if self.es_empaquetar else segundos_de(self.tiempo_1_pieza)
        self.teorico = a_decimales(Decimal(uno) / 60 * piezas, 1) if uno else None
        self.pct_dif = a_decimales((total - self.teorico) / self.teorico * 100, 1) if self.teorico else None

    def save(self, *args, **kwargs):
        if kwargs.get("update_fields") is None:
            if len(self.modelos) > 1 or self.modelo_pieza.strip().lower() == VARIOS_MODELOS.lower():
                self.modelo_pieza = VARIOS_MODELOS
            else:
                self.modelo_pieza = self.modelo_pieza.strip().upper()
            if self.es_empaquetar:
                self.tiempo_1_pieza = ""  # Empaquetar no lleva 1 pieza
            if not self.material and self.material_esperado:
                self.material = self.material_esperado  # se llena solo (regla 3)
            self.calcular()
        super().save(*args, **kwargs)

    @property
    def pct_texto(self):
        return f"{con_signo(self.pct_dif)} %" if self.pct_dif is not None else ""

    @property
    def desvio_texto(self):
        """Contra la mediana de las otras: −74 % · +53 %."""
        return f"{con_signo(self.desvio * 100)} %" if self.desvio is not None else ""

    @property
    def alerta_texto(self):
        """excluida +53 % · revisar +136 %."""
        return f"{self.get_alerta_display()} {self.desvio_texto}" if self.alerta else ""

    @property
    def modelos_texto(self):
        """Empaquetar: 'MKD-2 · 16, MT-2 · 8'; lo demás: el modelo."""
        if self.modelos:
            return ", ".join(f"{m['modelo']} · {m['piezas']}" for m in self.modelos)
        return self.modelo_pieza
    @property
    def origen_texto(self):
        if self.origen == self.Origen.IMPORTADA and self.importacion_id:
            return f"Importada {timezone.localtime(self.importacion.fecha):%d/%m/%Y} · fila {self.fila_hoja}"
        return self.get_origen_display()

    def resumen(self):
        """Para la bitácora: los datos capturados en una línea."""
        partes = [
            f"{self.fecha:%d/%m/%Y}", self.quien_midio, self.operador.nombre if self.operador_id else "",
            self.modelos_texto, f"{self.operacion_madre.nombre if self.operacion_madre_id else ''} › {self.operacion_nombre}",
            self.maquina.nombre if self.maquina_id else "", self.medida, self.get_material_display(),
            f"1 pza {self.tiempo_1_pieza}" if self.tiempo_1_pieza else "",
            f"{self.muestra_piezas} pzas en {self.muestra_tiempo_total}", self.observaciones,
        ]
        return " · ".join(p for p in partes if p)


class Bitacora(models.Model):
    """Regla 11: alta, cambio y baja de mediciones; aprobados, tiempos fijos y parámetros."""

    fecha = models.DateTimeField(auto_now_add=True, verbose_name="Cuándo")
    usuario = models.CharField(max_length=150, verbose_name="Quién")
    accion = models.CharField(max_length=40, verbose_name="Acción")
    objeto = models.CharField(max_length=255, verbose_name="Sobre qué")
    anterior = models.TextField(blank=True, default="", verbose_name="Valor anterior")
    nuevo = models.TextField(blank=True, default="", verbose_name="Valor nuevo")

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "Bitácora del estudio"
        verbose_name_plural = "Bitácora del estudio"

    def __str__(self):
        return f"{self.fecha:%d/%m/%Y %H:%M} · {self.accion} · {self.objeto}"

    @classmethod
    def anotar(cls, usuario, accion, objeto, anterior="", nuevo=""):
        return cls.objects.create(
            usuario=usuario or "Sin nombre", accion=accion, objeto=str(objeto)[:255],
            anterior=str(anterior or ""), nuevo=str(nuevo or ""),
        )