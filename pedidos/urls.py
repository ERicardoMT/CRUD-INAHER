from django.urls import path
from . import views
from .views import (
    PedidoListView,
    PedidoDetailView,
    PedidoCreateView,
    PedidoUpdateView,
)

app_name = "pedidos"

urlpatterns = [
    path("", PedidoListView.as_view(), name="lista"),
    path("nuevo/", PedidoCreateView.as_view(), name="crear"),
    path("<int:pk>/", PedidoDetailView.as_view(), name="detalle"),
    path("<int:pk>/editar/", PedidoUpdateView.as_view(), name="editar"),
    path("<int:pk>/estado/", views.cambiar_estado, name="cambiar_estado"),
    path("<int:pk>/entrega/", views.registrar_entrega, name="registrar_entrega"),
    path("entrega/<int:pk>/eliminar/", views.eliminar_entrega, name="eliminar_entrega"),
    path("<int:pk>/eliminar/", views.eliminar_pedidos, name="eliminar"),
    path("<int:pk>/imprimir/", views.imprimir_ficha, name="imprimir_ficha"),
    path("eliminar/", views.eliminar_pedidos, name="eliminar_seleccionados"),
    path("archivar/", views.archivar_pedidos, name="archivar"),
    path("desarchivar/", views.desarchivar_pedidos, name="desarchivar"),
    path("imprimir/", views.imprimir_listado, name="imprimir_listado"),
    path("exportar/", views.exportar_excel, name="exportar_excel"),
    path("bitacora/", views.bitacora, name="bitacora"),
    path("api/numero-disponible/", views.numero_disponible, name="numero_disponible"),
]
