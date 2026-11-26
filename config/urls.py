from django.contrib import admin

from designaciones import mi_lista
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView
from django.contrib.auth.decorators import login_not_required

urlpatterns = [
    # El login del admin pasa por el nuestro (tiene bloqueo por intentos fallidos)
    path("admin/login/", login_not_required(RedirectView.as_view(pattern_name="core:entrar", query_string=True))),
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
    path("pedidos/", include("pedidos.urls")),
    path("designacion/", include("designaciones.urls")),
    # Pantalla de los trabajadores (celular): cada quien ve solo su lista
    path("mi-lista/", mi_lista.mi_lista, name="mi_lista"),
    path("mi-lista/tarea/<int:pk>/marcar/", mi_lista.marcar, name="mi_lista_marcar"),
    path("mi-lista/tarea/<int:pk>/piezas/", mi_lista.anotar_piezas, name="mi_lista_piezas"),
    path("estudio-tiempos/", include("tiempos.urls")),
    path("archivo/", include("archivo.urls")),
    path("eficiencia/", include("eficiencia.urls")),
    path("por-operacion/", include("lista_trabajo.urls")),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)