from django.contrib import admin

from .models import Escalon, Maquina, Operario, TiempoFijo
@admin.register(Operario)
class OperarioAdmin(admin.ModelAdmin):
    list_display = ("nombre", "activo", "tarifa_hora")
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
