from django.urls import path

from . import views

app_name = "eficiencia"

urlpatterns = [
    path("", views.tareas, name="tareas"),
    path("por-operacion/", views.operaciones, name="operaciones"),
    path("minutos/", views.minutos, name="minutos"),
    path("direccion/", views.direccion, name="direccion"),
    path("exportar-todo/", views.exportar_todo, name="exportar_todo"),
    path("tarea/<int:pk>/min-real/", views.guardar_min_real, name="min_real"),
    path("estandar/<int:pk>/", views.cambiar_estandar, name="cambiar_estandar"),
    path("exportar/<str:tabla>/", views.exportar, name="exportar"),
]
