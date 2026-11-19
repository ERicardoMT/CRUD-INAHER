from django.urls import path
from . import views

app_name = "designaciones"

urlpatterns = [
    path("", views.designacion_hoy, name="hoy"),
    path("tarea/agregar/", views.agregar_item, name="agregar_item"),
    path("tarea/<int:pk>/check/", views.toggle_item_hecho, name="toggle_hecho"),
    path("tarea/<int:pk>/campo/", views.guardar_campo, name="guardar_campo"),
    path("tarea/<int:pk>/editar/", views.editar_item, name="editar_item"),
    path("tarea/<int:pk>/quitar/", views.eliminar_item, name="eliminar_item"),
    path("tareas/quitar/", views.quitar_seleccionadas, name="quitar_seleccionadas"),
    path("tareas/deshacer/", views.deshacer_quitar, name="deshacer_quitar"),
    path("tareas/asignar/", views.asignar_persona, name="asignar_persona"),
    path("moldes/<int:pk>/", views.actualizar_moldes, name="actualizar_moldes"),
    path("nuevo-dia/", views.nuevo_dia, name="nuevo_dia"),
    path("imprimir/", views.imprimir_lista, name="imprimir_lista"),
    path("exportar/", views.exportar_excel, name="exportar_excel"),
    path("api/operaciones-detalladas/", views.api_operaciones_detalladas, name="api_operaciones_detalladas"),
    path("api/pedido-info/", views.api_pedido_info, name="api_pedido_info"),
    path("api/ruta-pedido/", views.api_ruta_pedido, name="api_ruta_pedido"),
    path("api/minutos-ruta/", views.api_minutos_ruta, name="api_minutos_ruta"),
    path("cargar-ruta/", views.cargar_ruta, name="cargar_ruta"),
]
