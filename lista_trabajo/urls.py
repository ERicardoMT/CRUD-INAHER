from django.urls import path

from . import views

app_name = "lista_trabajo"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("imprimir/", views.imprimir, name="imprimir"),
    path("exportar/", views.exportar, name="exportar"),
]
