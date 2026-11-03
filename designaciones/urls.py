from django.urls import path
from . import views

app_name = "designaciones"

urlpatterns = [
    path("", views.designacion_hoy, name="hoy"),
    path("item/agregar/<int:designacion_id>/", views.agregar_item, name="agregar_item"),
    path("item/toggle/<int:pk>/", views.toggle_item_hecho, name="toggle_hecho"),
    path("item/editar/<int:pk>/", views.editar_item, name="editar_item"),
    path("item/eliminar/<int:pk>/", views.eliminar_item, name="eliminar_item"),
    path("moldes/actualizar/<int:pk>/", views.actualizar_moldes, name="actualizar_moldes"),
    path("api/operaciones-detalladas/", views.api_operaciones_detalladas, name="api_operaciones_detalladas"),
    path("api/pedido-info/", views.api_pedido_info, name="api_pedido_info"),
    path("item/vaciar-seleccionados/<int:designacion_id>/", views.vaciar_items_seleccionados, name="vaciar_items_seleccionados"),
    path("nuevo-dia/<int:designacion_id>/", views.nuevo_dia, name="nuevo_dia"),
    path("cargar-ruta/<int:designacion_id>/", views.cargar_ruta, name="cargar_ruta"),
]
