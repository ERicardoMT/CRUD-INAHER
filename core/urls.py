from django.urls import path
from . import views

app_name = "core"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("catalogos/", views.catalogos_config, name="catalogos"),
    path("catalogos/agregar-nuevas/", views.agregar_nuevas_config, name="agregar_nuevas_config"),
    path("catalogos/recalcular-tiempos/", views.recalcular_tiempos_config, name="recalcular_tiempos_config"),
    path("catalogos/<str:tipo>/guardar/", views.guardar_catalogo, name="guardar_catalogo"),
    path("catalogos/<str:tipo>/<int:pk>/eliminar/", views.eliminar_catalogo, name="eliminar_catalogo"),
    path("modulos/<slug:slug>/", views.modulo_pendiente, name="modulo_pendiente"),
]