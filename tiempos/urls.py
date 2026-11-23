from django.urls import path

from . import views

app_name = "tiempos"

urlpatterns = [
    path("", views.mediciones, name="lista"),
    path("medicion/nueva/", views.medicion, name="nueva"),
    path("medicion/<int:pk>/", views.medicion, name="editar"),
    path("medicion/<int:pk>/borrar/", views.borrar, name="borrar"),
    path("parametros/", views.parametros, name="parametros"),
    path("exportar/", views.exportar, name="exportar"),
    path("operaciones/", views.operaciones, name="operaciones"),
    path("operaciones/exportar/", views.exportar_operaciones, name="exportar_operaciones"),
    path("operacion/<int:pk>/", views.ver_operacion, name="operacion"),
    path("operacion/<int:pk>/aprobar/", views.aprobar, name="aprobar"),
    path("operacion/<int:pk>/tiempo-fijo/", views.tiempo_fijo, name="tiempo_fijo"),
    path("medicion/<int:pk>/al-catalogo/", views.agregar_nueva, name="agregar_nueva"),
    path("importar/", views.importar, name="importar"),
    path("importar/<int:pk>/deshacer/", views.deshacer_importacion, name="deshacer_importacion"),
]