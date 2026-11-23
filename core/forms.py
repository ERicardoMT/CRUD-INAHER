from django import forms
from decimal import Decimal
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from . import seguridad

from designaciones.models import Operario, Maquina, OperacionMadre, OperacionDetallada
from .models import Configuracion

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
    """Alta de operación: el minuto que se escribe aquí queda como su tiempo fijo (Estudio de tiempos, regla 10)."""

    min_estimado = forms.DecimalField(
        label="Min estimado por pieza", required=False, min_value=Decimal("0.01"), max_digits=7, decimal_places=2,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0.01", "placeholder": "opcional"}),
    )

    class Meta:
        model = OperacionDetallada
        fields = ["madre", "nombre", "maquina_sugerida", "activa"]
        widgets = {
            "madre": forms.Select(attrs={"class": "form-select"}),
            "nombre": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nombre detallado de la operación"}),
            "maquina_sugerida": forms.Select(attrs={"class": "form-select"}),
            "activa": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        
class ConfiguracionForm(forms.ModelForm):
    class Meta:
        model = Configuracion
        fields = ["turno_inicio", "turno_fin", "comida_minutos", "personas_en_planta", "tolerancia_pct", "minimo_medidas"]
        widgets = {
            "turno_inicio": forms.TimeInput(attrs={"class": "form-control", "type": "time"}, format="%H:%M"),
            "turno_fin": forms.TimeInput(attrs={"class": "form-control", "type": "time"}, format="%H:%M"),
            "comida_minutos": forms.NumberInput(attrs={"class": "form-control", "min": 0, "max": 600}),
            "personas_en_planta": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 500}),
            "tolerancia_pct": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 100}),
            "minimo_medidas": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 50}),
        }

    def clean(self):
        datos = super().clean()
        inicio, fin = datos.get("turno_inicio"), datos.get("turno_fin")
        if inicio and fin and fin <= inicio:
            self.add_error("turno_fin", "El fin del turno debe ser después del inicio.")
        return datos
    
class EntrarForm(AuthenticationForm):
    """
    Inicio de sesión. Django compara la contraseña cifrada y consulta con el ORM (parámetros, sin inyección SQL).
    Aquí se agrega el bloqueo por intentos fallidos y un mensaje que no revela si el usuario existe.
    """

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Usuario o contraseña incorrectos.",
        "bloqueado": "Demasiados intentos fallidos. Espera %(minutos)s minutos e inténtalo de nuevo.",
    }

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields["username"].label = "Usuario"
        self.fields["username"].widget.attrs.update({
            "class": "form-control", "autocomplete": "username", "autocapitalize": "none",
            "spellcheck": "false", "maxlength": 150, "autofocus": True,
        })
        self.fields["password"].widget.attrs.update({
            "class": "form-control", "autocomplete": "current-password", "maxlength": 128,
        })

    def clean(self):
        usuario = self.cleaned_data.get("username", "")
        if seguridad.esta_bloqueado(self.request, usuario):
            raise ValidationError(
                self.error_messages["bloqueado"], code="bloqueado",
                params={"minutos": settings.LOGIN_BLOQUEO_MINUTOS},
            )
        try:
            datos = super().clean()
        except ValidationError:
            seguridad.registrar_fallo(self.request, usuario)
            raise
        seguridad.limpiar(self.request, usuario)
        return datos
