from django.contrib import admin

from .models import Bitacora


@admin.register(Bitacora)
class BitacoraAdmin(admin.ModelAdmin):
    list_display = ("fecha", "usuario", "accion", "objeto")
    search_fields = ("usuario", "accion", "objeto")
    readonly_fields = ("fecha", "usuario", "accion", "objeto", "anterior", "nuevo")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False