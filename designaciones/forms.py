from django import forms
from .models import DesignacionDia, ItemDesignacion, Operario, Maquina, OperacionMadre, OperacionDetallada
from pedidos.models import Pedido


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
        ]
        widgets = {
            "quien": forms.Select(attrs={"class": "form-select"}),
            "pedido": forms.Select(attrs={"class": "form-select"}),
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
        self.fields["pedido"].queryset = Pedido.objects.exclude(estado=Pedido.Estado.TERMINADO)

