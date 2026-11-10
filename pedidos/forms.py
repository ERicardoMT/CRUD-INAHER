from django import forms
from django.core.exceptions import ValidationError
from django.forms import BaseInlineFormSet, inlineformset_factory

from .models import Cliente, Entrega, PartidaPedido, Pedido


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
            "detenido_fecha_esperada",
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
            "detenido_fecha_esperada": FechaInput(),
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

        # El número lo proporciona el SAE: no se modifica al editar.
        if self.instance.pk:
            self.fields["numero"].disabled = True
            self.fields["numero"].help_text = (
                "El número de pedido proviene del SAE y no se puede modificar."
            )
        self.fields["detenido_por"].help_text = ""
        # ENTREGADO solo se registra con fecha y cantidad (botón "Registrar entrega")
        if self.instance.estado != Pedido.Estado.ENTREGADO:
            self.fields["estado"].choices = [
                c for c in self.fields["estado"].choices if c[0] != Pedido.Estado.ENTREGADO
            ]
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
        if not datos.get("detenido"):
            datos["detenido_fecha_esperada"] = None
        return datos

    def save(self, commit=True):
        nombre = self.cleaned_data["cliente_nombre"].strip()
        cliente = None
        if nombre:
            cliente = Cliente.objects.filter(nombre__iexact=nombre).first() or Cliente.objects.create(nombre=nombre)
        self.instance.cliente = cliente
        # Si el usuario movió la casilla, la bandera queda "puesta a mano"
        if "detenido" in self.changed_data:
            self.instance.detenido_manual = bool(self.cleaned_data.get("detenido"))
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Detecta partidas que ya tienen al menos una tarea completada.
        for form in self.forms:
            form.tiene_avance = False

            if form.instance.pk:
                form.tiene_avance = (
                    form.instance.items_designacion
                    .filter(hecho=True)
                    .exists()
                )

    def clean(self):
        super().clean()

        if any(self.errors):
            return

        # Una partida con tareas completadas no se puede eliminar.
        protegidas = [
            form.instance.descripcion
            for form in self.forms
            if (
                form.instance.pk
                and form.cleaned_data.get("DELETE")
                and form.tiene_avance
            )
        ]

        if protegidas:
            nombres = ", ".join(protegidas)

            raise ValidationError(
                "No se pueden eliminar estas partidas porque ya tienen "
                f"tareas completadas: {nombres}. "
                "Solo se permite modificar su cantidad."
            )

        vivas = [
            form for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get("DELETE")
        ]

        if not vivas:
            raise ValidationError(
                "Captura al menos una partida con cantidad mayor a 0."
            )

PartidaFormSet = inlineformset_factory(
    Pedido,
    PartidaPedido,
    form=PartidaForm,
    formset=BasePartidaFormSet,
    extra=0,
    min_num=1,
    can_delete=True,
)


class EntregaForm(forms.ModelForm):
    class Meta:
        model = Entrega
        fields = ["fecha", "recibe", "paqueteria", "paqueteria_otra", "guia", "nota", "acuse"]
        labels = {"guia": "Número de guía de ESTA entrega"}
        widgets = {
            "fecha": FechaInput(),
            "recibe": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nombre"}),
            "paqueteria": forms.Select(attrs={"class": "form-select"}),
            "paqueteria_otra": forms.TextInput(attrs={"class": "form-control", "placeholder": "Escribe el nombre de la paquetería"}),
            "guia": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ej. 805312209875"}),
            "nota": forms.TextInput(attrs={"class": "form-control", "placeholder": "Opcional · factura, cajas, observaciones…"}),
            "acuse": forms.FileInput(attrs={"class": "form-control", "accept": "image/jpeg,image/png,image/webp"}),
        }

    def __init__(self, *args, pedido, **kwargs):
        super().__init__(*args, **kwargs)
        self.pedido = pedido
        self.fields["paqueteria"].required = True
        self.fields["paqueteria"].choices = [("", "Selecciona…")] + list(Entrega.Paqueteria.choices)

        self.filas = []
        for partida in pedido.partidas.all():
            nombre = f"partida_{partida.pk}"
            self.fields[nombre] = forms.IntegerField(
                required=False, min_value=0, max_value=partida.faltan, initial=partida.faltan,
                widget=forms.NumberInput(attrs={"class": "form-control", "inputmode": "numeric"}),
            )
            self.filas.append((partida, self[nombre]))

    def clean(self):
        datos = super().clean()
        paqueteria = datos.get("paqueteria")
        if paqueteria and paqueteria not in Entrega.SIN_GUIA and not datos.get("guia"):
            self.add_error("guia", "Captura la guía (solo es opcional si es flete propio o cliente recoge).")

        if paqueteria == Entrega.Paqueteria.OTRA:
            if not datos.get("paqueteria_otra"):
                self.add_error("paqueteria_otra", "Escribe el nombre de la paquetería.")
        else:
            datos["paqueteria_otra"] = ""

        self.cantidades = {p: datos.get(f"partida_{p.pk}") or 0 for p, _ in self.filas}
        total = sum(self.cantidades.values())
        faltan = self.pedido.cantidad_por_entregar
        if not faltan:
            raise ValidationError("Este pedido ya se entregó completo.")
        if not total:
            raise ValidationError("Captura al menos una pieza en alguna partida.")
        if total > faltan:
            raise ValidationError(f"Solo faltan {faltan} pzas por entregar.")
        self.instance.cantidad = total
        return datos
