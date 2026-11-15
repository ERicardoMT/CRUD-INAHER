from django.contrib import admin

from .models import Configuracion, DiaInhabil

admin.site.register(Configuracion)

@admin.register(DiaInhabil)
class DiaInhabilAdmin(admin.ModelAdmin):
    list_display = ("fecha", "motivo")