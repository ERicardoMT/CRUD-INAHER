from django.urls import path
from designaciones import rutas_editor

from . import configuracion, usuarios, views
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
    # Catálogos › Rutas de producción (editor propio)
    path("catalogos/rutas/", rutas_editor.lista, name="rutas"),
    path("catalogos/rutas/familia/nueva/", rutas_editor.familia_nueva, name="ruta_familia_nueva"),
    path("catalogos/rutas/familia/<int:pk>/", rutas_editor.familia, name="ruta_familia"),
    path("catalogos/rutas/familia/<int:familia_pk>/paso/nuevo/", rutas_editor.paso, name="ruta_paso_nuevo"),
    path("catalogos/rutas/familia/<int:familia_pk>/paso/<int:pk>/", rutas_editor.paso, name="ruta_paso"),
    path("catalogos/rutas/paso/<int:pk>/activo/", rutas_editor.paso_activo, name="ruta_paso_activo"),
    path("catalogos/rutas/paso/<int:pk>/quitar/", rutas_editor.paso_quitar, name="ruta_paso_quitar"),
    # Catálogos › Turno y eficiencia: tarifas y días que no se trabaja
    path("catalogos/tarifas/", configuracion.guardar_tarifas, name="guardar_tarifas"),
    path("catalogos/dias/agregar/", configuracion.agregar_dia, name="agregar_dia"),
    path("catalogos/dias/<int:pk>/quitar/", configuracion.quitar_dia, name="quitar_dia"),
    # Configuración › Usuarios
    path("configuracion/usuarios/", usuarios.lista, name="usuarios"),
    path("configuracion/usuarios/nuevo/", usuarios.nuevo, name="usuario_nuevo"),
    path("configuracion/usuarios/<int:pk>/", usuarios.editar, name="usuario_editar"),
    path("configuracion/usuarios/<int:pk>/contrasena/", usuarios.contrasena, name="usuario_contrasena"),
    path("configuracion/usuarios/<int:pk>/baja/", usuarios.baja, name="usuario_baja"),
    path("configuracion/usuarios/<int:pk>/reactivar/", usuarios.reactivar, name="usuario_reactivar"),
    path("modulos/<slug:slug>/", views.modulo_pendiente, name="modulo_pendiente"),
]