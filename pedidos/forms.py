from django import forms
from django.core.exceptions import ValidationError
from django.forms import BaseInlineFormSet, inlineformset_factory

from .models import Cliente, PartidaPedido, Pedido


def mensaje_numero_ocupado(pedido):
    """Aviso cuando el # del SAE ya existe (lo usan el formulario y la verificación en vivo)."""
    datos = ", ".join(filter(None, [
        pedido.cliente.nombre if pedido.cliente else "",
        pedido.fecha_captura.strftime("%d/%m/%Y") if pedido.fecha_captura else "",
    ]))
    return f"El pedido {pedido.numero} ya existe{f' ({datos})' if datos else ''}. Ábrelo o cambia el número."


class FechaInput(forms.DateInput):
    """Calendario nativo; el formato ISO es el que entiende <input type="date">."""
    input_type = "date"

    def __init__(self, attrs=None):
        super().__init__(attrs={"class": "form-control", **(attrs or {})}, format="%Y-%m-%d")


class PedidoForm(forms.ModelForm):
    cliente_nombre = forms.CharField(
        label="Cliente",
        required=False,
        max_length=150,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "list": "clientes-lista",
            "autocomplete": "off",
            "placeholder": "Escribe y te propone",
        }),
    )

    class Meta:
        model = Pedido
        fields = [
            "numero",
            "fecha_captura",
            "fecha_salida",
            "estado",
            "detenido",
            "detenido_por",
            "notas",
        ]
        labels = {
            "numero": "Número de pedido",
        }
        widgets = {
            "numero": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ej. 5091 o COT12961",
                "autocomplete": "off",
            }),
            "fecha_captura": FechaInput(),
            "fecha_salida": FechaInput(),
            "estado": forms.Select(attrs={"class": "form-select"}),
            "detenido": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "detenido_por": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Detenido por… material faltante · fecha esperada",
            }),
            "notas": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 2,
                "placeholder": "Lo que haga falta",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fecha_salida"].required = True
        self.fields["detenido_por"].help_text = ""
        if self.instance.cliente_id:
            self.initial["cliente_nombre"] = self.instance.cliente.nombre

    def clean_numero(self):
        numero = self.cleaned_data["numero"].strip()
        existente = Pedido.objects.numero(numero).exclude(pk=self.instance.pk).first()
        if existente:
            raise ValidationError(mensaje_numero_ocupado(existente))
        return numero

    def clean(self):
        datos = super().clean()
        captura, salida = datos.get("fecha_captura"), datos.get("fecha_salida")
        if captura and salida and salida < captura:
            self.add_error("fecha_salida", "La fecha de salida no puede ser antes de la fecha de captura.")

        motivo = (datos.get("detenido_por") or "").strip()
        if datos.get("detenido") and not motivo:
            self.add_error("detenido_por", "Escribe por qué está detenido.")
        datos["detenido_por"] = motivo if datos.get("detenido") else ""
        return datos

    def save(self, commit=True):
        nombre = self.cleaned_data["cliente_nombre"].strip()
        cliente = None
        if nombre:
            cliente = Cliente.objects.filter(nombre__iexact=nombre).first() or Cliente.objects.create(nombre=nombre)
        self.instance.cliente = cliente
        return super().save(commit)


class PartidaForm(forms.ModelForm):
    class Meta:
        model = PartidaPedido
        fields = ["cantidad", "descripcion"]
        widgets = {
            "cantidad": forms.NumberInput(attrs={
                "class": "form-control js-partida-cant",
                "min": 1,
                "inputmode": "numeric",
                "aria-label": "Cantidad de la partida",
            }),
            "descripcion": forms.TextInput(attrs={
                "class": "form-control js-partida-desc",
                "aria-label": "Descripción de la partida",
                "list": "modelos-lista",
                "autocomplete": "off",
                "placeholder": "Modelo y especificaciones (ej. MT-2 de 1/2 × 2 galv con pad)",
            }),
        }


class BasePartidaFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        vivas = [
            f for f in self.forms
            if f.cleaned_data and not f.cleaned_data.get("DELETE")
        ]
        if not vivas:
            raise ValidationError("Captura al menos una partida con cantidad mayor a 0.")


PartidaFormSet = inlineformset_factory(
    Pedido,
    PartidaPedido,
    form=PartidaForm,
    formset=BasePartidaFormSet,
    extra=0,
    min_num=1,
    can_delete=True,
)
