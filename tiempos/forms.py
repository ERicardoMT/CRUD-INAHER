from django import forms
from decimal import Decimal
from django.utils import timezone

from core.models import Configuracion
from designaciones.models import MADRE_EMPAQUETAR, Maquina, OperacionDetallada, OperacionMadre, Operario
from pedidos.fotos import comprimir_foto
from pedidos.models import max_5mb

from .models import MedicionTiempo, segundos_de, texto_mmss

NUEVA = "nueva"  # opción "No está: escribirla" de la operación detallada


def _valor(form, campo):
    """Lo que trae el formulario (o la medición que se edita) para ese campo."""
    if form.is_bound:
        return form.data.get(form.add_prefix(campo), "")
    return form.initial.get(campo) or getattr(form.instance, f"{campo}_id", None) or ""


class MedicionForm(forms.ModelForm):
    """Nueva medición y editar (ventana A de la página 4). Reglas 1 a 3."""

    detallada = forms.ChoiceField(label="Operación detallada", widget=forms.Select(attrs={"class": "form-select"}))

    class Meta:
        model = MedicionTiempo
        fields = [
            "fecha", "quien_midio", "operador", "operacion_madre", "detallada_nueva", "maquina",
            "modelo_pieza", "medida", "material", "tiempo_1_pieza", "muestra_piezas",
            "muestra_tiempo_total", "foto", "observaciones",
        ]
        widgets = {
            "fecha": forms.DateInput(attrs={"class": "form-control", "type": "date"}, format="%Y-%m-%d"),
            "quien_midio": forms.TextInput(attrs={"class": "form-control", "list": "lista-midio", "autocomplete": "off"}),
            "operador": forms.Select(attrs={"class": "form-select"}),
            "operacion_madre": forms.Select(attrs={"class": "form-select"}),
            "detallada_nueva": forms.TextInput(attrs={"class": "form-control", "placeholder": "Escribe la operación detallada"}),
            "maquina": forms.Select(attrs={"class": "form-select"}),
            "modelo_pieza": forms.TextInput(attrs={"class": "form-control", "placeholder": "ej. CFD-4"}),
            "medida": forms.TextInput(attrs={"class": "form-control", "placeholder": "ej. 3/4"}),
            "material": forms.Select(attrs={"class": "form-select"}),
            "tiempo_1_pieza": forms.TextInput(attrs={"class": "form-control", "placeholder": "1:19", "inputmode": "numeric"}),
            "muestra_piezas": forms.NumberInput(attrs={"class": "form-control", "min": 1, "inputmode": "numeric"}),
            "muestra_tiempo_total": forms.TextInput(attrs={"class": "form-control", "placeholder": "5:17", "inputmode": "numeric"}),
            "foto": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "observaciones": forms.TextInput(attrs={"class": "form-control", "placeholder": "opcional"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        actual = self.instance

        # Operador: personas activas (y la de la medición, aunque ya esté de baja)
        operadores = Operario.objects.filter(activo=True)
        if actual.operador_id:
            operadores = operadores | Operario.objects.filter(pk=actual.operador_id)
        self.fields["operador"].queryset = operadores.order_by("orden", "nombre")
        self.fields["operador"].required = True
        self.fields["operacion_madre"].queryset = OperacionMadre.objects.filter(activa=True)
        self.fields["operacion_madre"].required = True
        self.fields["material"].choices = [("", "—"), *MedicionTiempo.Material.choices]
        self.fields["muestra_piezas"].required = False  # en Empaquetar es la suma de los modelos

        # Detallada: solo las de esa madre y, al final, "No está: escribirla" (regla 3)
        madre_id = str(_valor(self, "operacion_madre"))
        self.madre = OperacionMadre.objects.filter(pk=madre_id).first() if madre_id.isdigit() else None
        detalladas = self.madre.detalles.filter(activa=True) if self.madre else OperacionDetallada.objects.none()
        self.fields["detallada"].choices = [
            ("", "— elegir —"), *[(d.pk, d.nombre) for d in detalladas], (NUEVA, "No está: escribirla"),
        ]
        if not self.is_bound and actual.pk:
            self.initial["detallada"] = actual.operacion_detallada_id or NUEVA

        # Máquina: solo las del tipo de esa madre, como en Designación diaria
        maquinas = Maquina.objects.filter(activa=True)
        if self.madre:
            maquinas = maquinas.filter(pk__in=[m.pk for m in self.madre.opciones_maquina()])
        self.fields["maquina"].queryset = maquinas
        self.fields["maquina"].empty_label = "— elegir —"

        # Empaquetar: renglones de modelo y piezas (página 10)
        if self.is_bound:
            self.modelos_filas = list(zip(self.data.getlist("empaque_modelo"), self.data.getlist("empaque_piezas")))
        else:
            self.modelos_filas = [(m["modelo"], m["piezas"]) for m in actual.modelos] or [("", "")]

    @property
    def es_empaquetar(self):
        return bool(self.madre) and self.madre.nombre == MADRE_EMPAQUETAR

    def clean_fecha(self):
        fecha = self.cleaned_data["fecha"]
        if fecha > timezone.localdate():
            raise forms.ValidationError("No se aceptan fechas futuras.")
        return fecha

    def clean_tiempo_1_pieza(self):
        return texto_mmss(segundos_de(self.cleaned_data.get("tiempo_1_pieza")))

    def clean_muestra_tiempo_total(self):
        segundos = segundos_de(self.cleaned_data.get("muestra_tiempo_total"))
        if not segundos:
            raise forms.ValidationError("Escribe el tiempo total de la muestra.")
        return texto_mmss(segundos)

    def clean_foto(self):
        """Foto tomada con el celular o subida: 5 MB máximo y se comprime, como el acuse de entrega."""
        archivo = self.cleaned_data.get("foto")
        if not archivo or not hasattr(archivo, "content_type"):  # no se subió foto nueva
            return archivo
        max_5mb(archivo)
        return comprimir_foto(archivo)

    def clean(self):
        datos = super().clean()
        madre, elegida = datos.get("operacion_madre"), datos.get("detallada")
        if not madre:
            return datos

        # Operación detallada: del catálogo de esa madre, o escrita a mano (queda NUEVA)
        operacion = None
        if elegida == NUEVA:
            texto = " ".join((datos.get("detallada_nueva") or "").split())
            if not texto:
                self.add_error("detallada_nueva", "Escribe la operación detallada.")
            operacion = madre.detalles.filter(nombre__iexact=texto).first() if texto else None
            datos["detallada_nueva"] = "" if operacion else texto
        elif elegida:
            operacion = madre.detalles.filter(pk=elegida).first()
            datos["detallada_nueva"] = ""
        self.instance.operacion_detallada = operacion

        # Empaquetar: modelo obligatorio; la muestra es la suma de las piezas de cada modelo
        if self.es_empaquetar:
            filas = []
            for modelo, piezas in self.modelos_filas:
                modelo, piezas = " ".join(modelo.split()).upper()[:60], str(piezas).strip()
                if modelo or piezas:
                    if not modelo or not piezas.isdigit() or int(piezas) < 1:
                        self.add_error(None, "Cada modelo lleva su nombre y sus piezas (más de 0).")
                        break
                    filas.append({"modelo": modelo, "piezas": int(piezas)})
            if not filas:
                self.add_error(None, "En Empaquetar el modelo es obligatorio: escribe el modelo y sus piezas.")
            self.instance.modelos = filas
            datos["modelo_pieza"] = filas[0]["modelo"] if filas else ""
            datos["muestra_piezas"] = sum(f["piezas"] for f in filas) or None
            datos["tiempo_1_pieza"] = ""
        else:
            self.instance.modelos = []
            if not datos.get("muestra_piezas"):
                self.add_error("muestra_piezas", "Escribe cuántas piezas tiene la muestra (más de 0).")
        return datos
class ParametrosForm(forms.ModelForm):
    """Tolerancia y desvío máximo entre muestras: solo el administrador (lápiz de la página 1)."""

    class Meta:
        model = Configuracion
        fields = ["estudio_tolerancia_pct", "estudio_desvio_pct"]
        widgets = {
            "estudio_tolerancia_pct": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 100}),
            "estudio_desvio_pct": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 500}),
        }

class AprobarForm(forms.Form):
    """Ventana C: minutos mayores que 0 y con decimales · motivo opcional (regla 6)."""

    minutos = forms.DecimalField(
        label="Min aprobado", min_value=Decimal("0.0001"), max_digits=10, decimal_places=4,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "any", "min": "0", "inputmode": "decimal", "autofocus": True}),
    )
    motivo = forms.CharField(
        label="Motivo", required=False, max_length=200,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "ej. depende del modelo; se toma el de MKD"}),
    )


class TiempoFijoForm(forms.Form):
    """⋮ › Tiempo fijo (regla 7)."""

    minutos = forms.DecimalField(
        label="Minutos", min_value=Decimal("0.01"), max_digits=7, decimal_places=2,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0.01", "inputmode": "decimal", "autofocus": True}),
    )
    por_pedido = forms.BooleanField(
        label="Por pedido (no se multiplica por las piezas)", required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )        