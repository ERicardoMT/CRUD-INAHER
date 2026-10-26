from django import forms

from .models import Pedido


class PedidoForm(forms.ModelForm):

    class Meta:
        model = Pedido

        fields = [
            "numero",
            "descripcion",
            "cantidad",
            "fecha_salida",
            "estado",
            "notas",
        ]

        widgets = {
            "numero": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ej. 5049",
            }),

            "descripcion": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": (
                    "Productos, modelos y especificaciones"
                ),
            }),

            "cantidad": forms.NumberInput(attrs={
                "class": "form-control",
                "min": 1,
            }),

            "fecha_salida": forms.DateInput(attrs={
                "class": "form-control",
                "type": "date",
            }),

            "estado": forms.Select(attrs={
                "class": "form-select",
            }),

            "notas": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 2,
                "placeholder": "Observaciones opcionales",
            }),
        }