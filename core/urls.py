from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.inicio, name="inicio"),

    path(
        "modulos/<slug:slug>/",
        views.modulo_pendiente,
        name="modulo_pendiente",
    ),
]