from django.contrib import admin

from .models import Cliente, PartidaPedido, Pedido


class PartidaInline(admin.TabularInline):
    model = PartidaPedido
    extra = 0


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = (
        "numero",
        "cliente",
        "cantidad",
        "fecha_captura",
        "fecha_salida",
        "estado",
        "detenido",
    )

    list_filter = (
        "estado",
        "detenido",
        "fecha_salida",
    )

    search_fields = (
        "numero",
        "descripcion",
        "cliente__nombre",
    )

    inlines = [PartidaInline]

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        form.instance.actualizar_resumen()


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    search_fields = ("nombre",)
