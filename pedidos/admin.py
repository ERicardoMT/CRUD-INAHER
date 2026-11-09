from django.contrib import admin

from .models import Cliente, MovimientoPedido, PartidaPedido, Pedido


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
        "archivado",
    )

    list_filter = (
        "estado",
        "detenido",
        "archivado",
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


@admin.register(MovimientoPedido)
class MovimientoPedidoAdmin(admin.ModelAdmin):
    list_display = ("fecha", "accion", "pedido_numero", "usuario", "detalle")
    list_filter = ("accion",)
    search_fields = ("pedido_numero", "usuario", "detalle")

    def has_change_permission(self, request, obj=None):
        return False
