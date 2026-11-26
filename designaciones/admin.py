from django import forms
from django.contrib import admin

from .models import Escalon, FamiliaRuta, Maquina, Operario, PasoRuta, TiempoFijo
@admin.register(Operario)
class OperarioAdmin(admin.ModelAdmin):
    list_display = ("nombre", "usuario", "activo", "tarifa_hora")
    autocomplete_fields = ("usuario",)
    list_editable = ("tarifa_hora",)


@admin.register(Maquina)
class MaquinaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "tipo", "activa", "tarifa_hora")
    list_editable = ("tarifa_hora",)


@admin.register(TiempoFijo)
class TiempoFijoAdmin(admin.ModelAdmin):
    list_display = ("operacion", "minutos", "por_pedido")


@admin.register(Escalon)
class EscalonAdmin(admin.ModelAdmin):
    list_display = ("operacion", "hasta", "minutos")

class FamiliaRutaForm(forms.ModelForm):
    class Meta:
        model = FamiliaRuta
        fields = "__all__"
        widgets = {
            "modelos": forms.Textarea(
                attrs={"rows": 2, "class": "ruta-texto-compacto"}
            ),
            "descripcion": forms.Textarea(
                attrs={"rows": 3, "class": "ruta-texto-compacto"}
            ),
        }


class PasoRutaForm(forms.ModelForm):
    class Meta:
        model = PasoRuta
        fields = "__all__"
        widgets = {
            "detallada": forms.TextInput(
                attrs={"class": "ruta-campo-largo"}
            ),
            "condicion": forms.TextInput(
                attrs={"class": "ruta-campo-largo"}
            ),
            "nota": forms.Textarea(
                attrs={"rows": 2, "class": "ruta-texto-compacto"}
            ),
        }

class PasoRutaInline(admin.StackedInline):
    model = PasoRuta
    extra = 0

    fields = (("orden", "activo"), "madre", "detallada", "condicion", "nota")

    show_change_link = True


@admin.register(FamiliaRuta)
class FamiliaRutaAdmin(admin.ModelAdmin):
    form = FamiliaRutaForm
    fields = ("nombre", "modelos", "descripcion", ("orden", "activa"))
    list_display = (
        "nombre",
        "orden",
        "activa",
    )

    list_editable = (
        "orden",
        "activa",
    )

    search_fields = (
        "nombre",
        "modelos",
        "descripcion",
    )

    inlines = (PasoRutaInline,)

    class Media:
        css = {"all": ("designaciones/css/admin_rutas.css",)}


@admin.register(PasoRuta)
class PasoRutaAdmin(admin.ModelAdmin):
    form = PasoRutaForm
    list_display = (
        "familia",
        "orden",
        "madre",
        "detallada",
        "condicion",
        "activo",
    )

    list_filter = (
        "familia",
        "madre",
        "activo",
    )

    list_editable = (
        "orden",
        "activo",
    )

    search_fields = (
        "familia__nombre",
        "madre__nombre",
        "detallada",
        "condicion",
    )

    list_per_page = 50

    class Media:
        css = {"all": ("designaciones/css/admin_rutas.css",)}
