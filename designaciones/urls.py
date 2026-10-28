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
    # APIs para actualización dinámica
    path("api/operaciones-detalladas/", views.api_operaciones_detalladas, name="api_operaciones_detalladas"),
    path("api/pedido-info/", views.api_pedido_info, name="api_pedido_info"),
]

