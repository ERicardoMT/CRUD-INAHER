from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
    path("pedidos/", include("pedidos.urls")),
    path("designacion/", include("designaciones.urls")),
    path("estudio-tiempos/", include("tiempos.urls"))
]