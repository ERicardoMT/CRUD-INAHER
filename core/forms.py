from django import forms
from designaciones.models import Operario, Maquina, OperacionMadre, OperacionDetallada


class OperarioForm(forms.ModelForm):
    class Meta:
        model = Operario
        fields = ["nombre", "orden", "activo"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nombre del operario"}),
            "orden": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "activo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class MaquinaForm(forms.ModelForm):
    class Meta:
        model = Maquina
        fields = ["nombre", "tipo", "activa"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ej. Torno CNC Hermabro"}),
            "tipo": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ej. Torno CNC"}),
            "activa": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class OperacionMadreForm(forms.ModelForm):
    class Meta:
        model = OperacionMadre
        fields = ["nombre", "tipo_maquina", "activa"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ej. Cortar en sierra cinta"}),
            "tipo_maquina": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ej. Sierra cinta / Manual"}),
            "activa": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class OperacionDetalladaForm(forms.ModelForm):
    class Meta:
        model = OperacionDetallada
        fields = ["madre", "nombre", "maquina_sugerida", "minutos_estandar", "activa"]
        widgets = {
            "madre": forms.Select(attrs={"class": "form-select"}),
            "nombre": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nombre detallado de la operación"}),
            "maquina_sugerida": forms.Select(attrs={"class": "form-select"}),
            "minutos_estandar": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": 0}),
            "activa": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }