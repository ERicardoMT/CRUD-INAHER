from django.urls import path
from . import views
from .views import (
    PedidoListView,
    PedidoDetailView,
    PedidoCreateView,
    PedidoUpdateView,
    PedidoDeleteView,
)

app_name = "pedidos"

urlpatterns = [
    path("", PedidoListView.as_view(), name="lista"),
    path("nuevo/", PedidoCreateView.as_view(), name="crear"),
    path("<int:pk>/", PedidoDetailView.as_view(), name="detalle"),
    path("<int:pk>/editar/", PedidoUpdateView.as_view(), name="editar"),
    path("<int:pk>/estado/", views.cambiar_estado, name="cambiar_estado"),
    path("<int:pk>/eliminar/", PedidoDeleteView.as_view(), name="eliminar"),
    path("vaciar-seleccionados/", views.vaciar_pedidos_seleccionados, name="vaciar_seleccionados"),
    path("api/numero-disponible/", views.numero_disponible, name="numero_disponible"),
]
