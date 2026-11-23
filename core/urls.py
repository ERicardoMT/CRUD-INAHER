from django.urls import path
from . import views
from django.contrib.auth import views as auth_views

from .forms import EntrarForm

app_name = "core"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path(
        "entrar/",
        auth_views.LoginView.as_view(
            template_name="core/entrar.html", authentication_form=EntrarForm, redirect_authenticated_user=True,
        ),
        name="entrar",
    ),
    path("salir/", auth_views.LogoutView.as_view(), name="salir"),
    path("catalogos/", views.catalogos_config, name="catalogos"),
    path("catalogos/configuracion/", views.guardar_configuracion, name="guardar_configuracion"),
    path("catalogos/<str:tipo>/guardar/", views.guardar_catalogo, name="guardar_catalogo"),
    path("catalogos/<str:tipo>/<int:pk>/eliminar/", views.eliminar_catalogo, name="eliminar_catalogo"),
    path("modulos/<slug:slug>/", views.modulo_pendiente, name="modulo_pendiente"),
]