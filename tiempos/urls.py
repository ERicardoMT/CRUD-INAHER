from django.urls import path
from . import views

app_name = "tiempos"

urlpatterns = [
    path("", views.estudio_tiempos_list, name="lista"),
    path("nueva/", views.medicion_crear, name="crear"),
    path("eliminar/<int:pk>/", views.medicion_eliminar, name="eliminar"),
]