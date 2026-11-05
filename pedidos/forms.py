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
            "detenido_por",
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

            "detenido_por": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Solo si está detenido, ej. Base MT-2 · llega 12 nov",
            }),

            "notas": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 2,
                "placeholder": "Observaciones opcionales",
            }),
        }