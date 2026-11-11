from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from pedidos.forms import FechaInput
from pedidos.models import Pago, Pedido


class FacturaForm(forms.ModelForm):
    """FACTURADO: con factura (fecha de hoy ya puesta + folio) o no pidió factura."""

    class Meta:
        model = Pedido
        fields = ["factura_estado", "factura_fecha", "factura_folio", "factura_nota"]
        labels = {"factura_fecha": "Fecha de factura", "factura_folio": "Folio", "factura_nota": "Nota"}
        widgets = {
            "factura_estado": forms.RadioSelect(attrs={"class": "form-check-input"}),
            "factura_fecha": FechaInput(),
            "factura_folio": forms.TextInput(attrs={"class": "form-control", "placeholder": "F-2231", "autocomplete": "off", "autofocus": True}),
            "factura_nota": forms.TextInput(attrs={"class": "form-control", "placeholder": "…"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["factura_estado"].choices = [c for c in Pedido.Factura.choices if c[0] != Pedido.Factura.PENDIENTE]
        if self.instance.factura_estado == Pedido.Factura.PENDIENTE:
            self.initial["factura_estado"] = Pedido.Factura.FACTURADO
        if not self.instance.factura_fecha:
            self.initial["factura_fecha"] = timezone.localdate()

    def clean_factura_folio(self):
        return self.cleaned_data["factura_folio"].strip().upper()

    def clean(self):
        datos = super().clean()
        if datos.get("factura_estado") == Pedido.Factura.FACTURADO:
            if not datos.get("factura_folio"):
                self.add_error("factura_folio", "Captura el folio de la factura.")
            if not datos.get("factura_fecha"):
                self.add_error("factura_fecha", "Captura la fecha de la factura.")
        else:
            datos["factura_fecha"], datos["factura_folio"] = None, ""
        return datos


class PagoForm(forms.ModelForm):
    """PAGADO: acepta varios pagos; solo una liquidación."""

    class Meta:
        model = Pago
        fields = ["fecha", "tipo", "forma", "nota"]
        widgets = {
            "fecha": FechaInput(),
            "tipo": forms.Select(attrs={"class": "form-select"}),
            "forma": forms.Select(attrs={"class": "form-select"}),
            "nota": forms.TextInput(attrs={"class": "form-control", "placeholder": "referencia…"}),
        }

    def __init__(self, *args, pedido, **kwargs):
        super().__init__(*args, **kwargs)
        self.pedido = pedido

    def clean_tipo(self):
        tipo = self.cleaned_data["tipo"]
        if tipo == Pago.Tipo.LIQUIDACION and self.pedido.liquidacion:
            raise ValidationError("Este pedido ya está liquidado. Quita la liquidación para corregirla.")
        return tipo
