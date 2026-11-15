from django.contrib import admin

from .models import CambioEstandar

@admin.register(CambioEstandar)
class CambioEstandarAdmin(admin.ModelAdmin):
    list_display = ("fecha", "operacion", "anterior", "nuevo", "medidas", "usuario")
    list_select_related = ("operacion",)
