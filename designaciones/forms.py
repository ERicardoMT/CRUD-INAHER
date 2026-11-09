from django import forms
from .models import DesignacionDia, ItemDesignacion, Operario, Maquina, OperacionMadre, OperacionDetallada
from pedidos.models import PartidaPedido, Pedido


class DesignacionDiaForm(forms.ModelForm):
    class Meta:
        model = DesignacionDia
        fields = ["molde_1", "molde_2", "notas"]
        widgets = {
            "molde_1": forms.TextInput(attrs={
                "class": "form-control form-control-sm",
                "placeholder": "Ej. Molde IVH-4 / R-4",
            }),
            "molde_2": forms.TextInput(attrs={
                "class": "form-control form-control-sm",
                "placeholder": "Ej. Molde Nivelador MT-2",
            }),
            "notas": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 2,
                "placeholder": "Observaciones generales de la jornada...",
            }),
        }


class ItemDesignacionForm(forms.ModelForm):
    class Meta:
        model = ItemDesignacion
        fields = [
            "quien",
            "pedido",
            "partida",
            "es_stock",
            "paso",
            "descripcion_manual",
            "operacion_madre",
            "operacion_detallada",
            "maquina",
            "detalle",
            "cantidad",
            "minutos",
            "hecho",
            "bloqueado_por",
        ]
        widgets = {
            "quien": forms.Select(attrs={"class": "form-select"}),
            "pedido": forms.Select(attrs={"class": "form-select"}),
            "partida": forms.Select(attrs={"class": "form-select"}),
            "bloqueado_por": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Vacío si no está bloqueada · ej. Base MT-2 · llega 12 nov",
            }),
            "es_stock": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "paso": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "descripcion_manual": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Solo si es para stock o sin pedido en lista",
            }),
            "operacion_madre": forms.Select(attrs={"class": "form-select"}),
            "operacion_detallada": forms.Select(attrs={"class": "form-select"}),
            "maquina": forms.Select(attrs={"class": "form-select"}),
            "detalle": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Medida, tolerancia, indicación técnica",
            }),
            "cantidad": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "minutos": forms.NumberInput(attrs={
                "class": "form-control",
                "placeholder": "Auto según tiempo estándar si se deja 0",
            }),
            "hecho": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Mostrar solo registros activos en selectores
        self.fields["quien"].queryset = Operario.objects.filter(activo=True)
        self.fields["maquina"].queryset = Maquina.objects.filter(activa=True)
        self.fields["operacion_madre"].queryset = OperacionMadre.objects.filter(activa=True)
        self.fields["operacion_detallada"].queryset = OperacionDetallada.objects.filter(activa=True)
        pedidos = Pedido.objects.carga_planta()
        if self.instance.pedido_id:
            pedidos = pedidos | Pedido.objects.filter(pk=self.instance.pedido_id)
        self.fields["pedido"].queryset = pedidos

        # Partida: solo las del pedido elegido (el JS las recarga al cambiar de pedido)
        pedido_id = self.data.get(self.add_prefix("pedido")) if self.is_bound else self.instance.pedido_id
        self.fields["partida"].queryset = (
            PartidaPedido.objects.filter(pedido_id=pedido_id) if str(pedido_id or "").isdigit()
            else PartidaPedido.objects.none()
        )
        self.fields["partida"].empty_label = "Todo el pedido (p. ej. Empaquetar)"
        self.fields["partida"].label_from_instance = lambda x: f"{x.cantidad} · {x.descripcion}"

    def clean(self):
        datos = super().clean()
        partida, pedido = datos.get("partida"), datos.get("pedido")
        if partida and partida.pedido_id != getattr(pedido, "pk", None):
            self.add_error("partida", "Esa partida no es del pedido elegido.")
        datos["bloqueado_por"] = (datos.get("bloqueado_por") or "").strip()
        return datos

