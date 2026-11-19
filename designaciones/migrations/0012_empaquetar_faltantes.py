from decimal import Decimal

from django.db import migrations

# Operaciones de la madre Empaquetar que faltaban en el catálogo (Designación v2, regla 2).
# "Contar y revisar" lleva el nombre exacto que manda el motor de rutas.
FIJO = ("Empaquetar pedido extra grande", Decimal("15"))
ESCALONADA = ("Contar y revisar producto de compra", [(999, "3"), (5000, "6"), (10000, "10"), (None, "15")])


def crear(apps, schema_editor):
    Madre = apps.get_model("designaciones", "OperacionMadre")
    Detallada = apps.get_model("designaciones", "OperacionDetallada")
    TiempoFijo = apps.get_model("designaciones", "TiempoFijo")
    Escalon = apps.get_model("designaciones", "Escalon")
    madre = Madre.objects.filter(nombre="Empaquetar").first()
    if not madre:  # base nueva sin catálogo: no hay nada que completar
        return

    nombre, minutos = FIJO
    operacion, _ = Detallada.objects.get_or_create(madre=madre, nombre=nombre)
    TiempoFijo.objects.get_or_create(operacion=operacion, defaults={"minutos": minutos, "por_pedido": True})

    nombre, cortes = ESCALONADA
    operacion, _ = Detallada.objects.get_or_create(madre=madre, nombre=nombre)
    if not Escalon.objects.filter(operacion=operacion).exists():
        Escalon.objects.bulk_create(
            Escalon(operacion=operacion, hasta=hasta, minutos=Decimal(m)) for hasta, m in cortes
        )


class Migration(migrations.Migration):

    dependencies = [
        ("designaciones", "0011_minpz_cuatro_decimales"),
    ]

    operations = [migrations.RunPython(crear, migrations.RunPython.noop)]
