from django import forms
from .models import MedicionTiempo


class MedicionTiempoForm(forms.ModelForm):
    class Meta:
        model = MedicionTiempo
        fields = [
            "fecha", "quien_midio", "operador", "modelo_pieza",
            "operacion_madre", "operacion_detallada", "maquina",
            "medida", "material", "tiempo_1_pieza",
            "muestra_piezas", "muestra_tiempo_total", "foto_url", "observaciones"
        ]
        widgets = {
            "fecha": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "quien_midio": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ej. Axel / Frida"}),
            "operador": forms.Select(attrs={"class": "form-select"}),
            "modelo_pieza": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ej. cortar varilla 3/4"}),
            "operacion_madre": forms.Select(attrs={"class": "form-select"}),
            "operacion_detallada": forms.Select(attrs={"class": "form-select"}),
            "maquina": forms.Select(attrs={"class": "form-select"}),
            "medida": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ej. 3/4, 5/8"}),
            "material": forms.Select(attrs={"class": "form-select"}),
            "tiempo_1_pieza": forms.TextInput(attrs={"class": "form-control", "placeholder": "mm:ss (Ej. 00:20)"}),
            "muestra_piezas": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "muestra_tiempo_total": forms.TextInput(attrs={"class": "form-control", "placeholder": "mm:ss (Ej. 01:18)"}),
            "foto_url": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://..."}),
            "observaciones": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }