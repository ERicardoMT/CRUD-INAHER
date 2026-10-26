from django.contrib import admin

from .models import Pedido


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = (
        "numero",
        "cantidad",
        "fecha_salida",
        "estado",
    )

    list_filter = (
        "estado",
        "fecha_salida",
    )

    search_fields = (
        "numero",
        "descripcion",
    )