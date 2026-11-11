from django.urls import path

from . import views

app_name = "archivo"

urlpatterns = [
    path("", views.pedidos_archivados, name="pedidos"),
    path("imprimir/", views.imprimir_pedidos, name="imprimir"),
    path("exportar/", views.exportar_pedidos, name="exportar"),
    path("buscar/", views.buscar, name="buscar"),
    path("<int:pk>/facturado/", views.facturado, name="facturado"),
    path("<int:pk>/pagado/", views.pagado, name="pagado"),
    path("pago/<int:pk>/quitar/", views.quitar_pago, name="quitar_pago"),
    path("tareas/", views.tareas_cerradas, name="tareas"),
    path("tareas/exportar/", views.exportar_tareas, name="exportar_tareas"),
]
