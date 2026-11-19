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
    """
    Agregar / editar tarea (regla 6). Obligatorias: operación madre y detallada.
    Opcionales: pedido y partida (vacío = STOCK), paso, quién, máquina, cantidad y detalle.
    """

    class Meta:
        model = ItemDesignacion
        fields = [
            "pedido",
            "partida",
            "paso",
            "quien",
            "operacion_madre",
            "operacion_detallada",
            "maquina",
            "cantidad",
            "min_estimado_pz",
            "detalle",
            "bloqueado_por",
        ]
        labels = {
            "pedido": "Pedido",
            "quien": "Quién",
            "operacion_madre": "Operación madre",
            "operacion_detallada": "Operación detallada",
            "cantidad": "Cantidad",
        }
        widgets = {
            "pedido": forms.Select(attrs={"class": "form-select"}),
            "partida": forms.Select(attrs={"class": "form-select"}),
            "paso": forms.NumberInput(attrs={"class": "form-control", "min": 0, "placeholder": "—"}),
            "quien": forms.Select(attrs={"class": "form-select"}),
            "operacion_madre": forms.Select(attrs={"class": "form-select"}),
            "operacion_detallada": forms.Select(attrs={"class": "form-select"}),
            "maquina": forms.Select(attrs={"class": "form-select"}),
            "cantidad": forms.NumberInput(attrs={"class": "form-control", "min": 0, "inputmode": "numeric"}),
            "min_estimado_pz": forms.NumberInput(attrs={
                "class": "form-control", "min": "0.01", "step": "0.01", "inputmode": "decimal",
                "placeholder": "Ej. 0.5",
            }),
            "detalle": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Medida, material, para qué es",
            }),
            "bloqueado_por": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Vacío si no está bloqueada · ej. Base MT-2 · llega 12 nov",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["quien"].queryset = Operario.objects.filter(activo=True)
        self.fields["quien"].required = False
        self.fields["quien"].empty_label = "sin asignar"
        self.fields["maquina"].queryset = Maquina.objects.filter(activa=True)
        self.fields["maquina"].empty_label = "— elegir —"
        self.fields["operacion_madre"].queryset = OperacionMadre.objects.filter(activa=True)
        self.fields["operacion_detallada"].queryset = OperacionDetallada.objects.filter(activa=True).select_related("madre")
        self.fields["paso"].required = False
        self.fields["cantidad"].required = False

        pedidos = Pedido.objects.carga_planta()
        if self.instance.pedido_id:
            pedidos = pedidos | Pedido.objects.filter(pk=self.instance.pedido_id)
        self.fields["pedido"].queryset = pedidos
        self.fields["pedido"].required = False
        self.fields["pedido"].empty_label = "— sin pedido —"

        # Partida: solo las del pedido elegido (el JS las recarga al cambiar de pedido)
        pedido_id = self.data.get(self.add_prefix("pedido")) if self.is_bound else self.instance.pedido_id
        self.fields["partida"].queryset = (
            PartidaPedido.objects.filter(pedido_id=pedido_id) if str(pedido_id or "").isdigit()
            else PartidaPedido.objects.none()
        )
        self.fields["partida"].empty_label = "Todo el pedido"
        self.fields["partida"].label_from_instance = lambda x: f"{x.cantidad} · {x.descripcion}"

        # La detallada depende de la madre elegida
        madre_id = self.data.get(self.add_prefix("operacion_madre")) if self.is_bound else self.instance.operacion_madre_id
        if str(madre_id or "").isdigit():
            self.fields["operacion_detallada"].queryset = self.fields["operacion_detallada"].queryset.filter(madre_id=madre_id)

    def clean(self):
        datos = super().clean()
        pedido, partida = datos.get("pedido"), datos.get("partida")
        madre, detallada = datos.get("operacion_madre"), datos.get("operacion_detallada")
        maquina, cantidad = datos.get("maquina"), datos.get("cantidad")

        if partida and partida.pedido_id != getattr(pedido, "pk", None):
            self.add_error("partida", "Esa partida no es del pedido elegido.")
        if madre and detallada and detallada.madre_id != madre.pk:
            self.add_error("operacion_detallada", "La operación detallada tiene que ser de esa madre.")

        especial = bool(detallada and detallada.es_tarea_especial)
        if especial and not datos.get("min_estimado_pz"):
            self.add_error("min_estimado_pz", "La tarea especial necesita los min estimados por pieza.")
        if not especial:
            datos["min_estimado_pz"] = None
        if maquina and madre and not especial and madre.tipos and maquina not in madre.opciones_maquina():
            self.add_error("maquina", "Esa máquina no es de los tipos de esa operación.")

        if cantidad is None:
            # Con pedido, Cant propone la de la partida (Empaquetar: el total del pedido)
            datos["cantidad"] = partida.cantidad if partida else (pedido.cantidad if pedido else 0)
        elif self.instance.pk and datos["cantidad"] < self.instance.hechas:
            self.add_error("cantidad", f"No puede ser menor que Hechas ({self.instance.hechas}).")

        datos["paso"] = datos.get("paso") or 0
        datos["bloqueado_por"] = (datos.get("bloqueado_por") or "").strip()
        datos["detalle"] = (datos.get("detalle") or "").strip()
        return datos
