from decimal import Decimal

from django.db import migrations

# Regla D del PDF (13-nov-2026). Solo se crean si la operación existe en el catálogo.
TIEMPOS_FIJOS = [
    ("Empaquetar pedido chico", "3", True),
    ("Empaquetar pedido mediano", "6", True),
    ("Empaquetar pedido grande", "10", True),
    ("Empaquetar pedido extra grande", "15", True),
    ("Pegamento 1 herraje Chemlok", "45", False),
]
ESCALONES = ("Contar y revisar productos de compra y venta", [(999, "3"), (5000, "6"), (10000, "10"), (None, "15")])


def llenar(apps, schema_editor):
    Detallada = apps.get_model("designaciones", "OperacionDetallada")
    TiempoFijo = apps.get_model("designaciones", "TiempoFijo")
    Escalon = apps.get_model("designaciones", "Escalon")
    Item = apps.get_model("designaciones", "ItemDesignacion")

    for nombre, minutos, por_pedido in TIEMPOS_FIJOS:
        operacion = Detallada.objects.filter(nombre__iexact=nombre).first()
        if operacion:
            TiempoFijo.objects.get_or_create(
                operacion=operacion, defaults={"minutos": Decimal(minutos), "por_pedido": por_pedido},
            )

    nombre, cortes = ESCALONES
    operacion = Detallada.objects.filter(nombre__iexact=nombre).first()
    if operacion and not Escalon.objects.filter(operacion=operacion).exists():
        for hasta, minutos in cortes:
            Escalon.objects.create(operacion=operacion, hasta=hasta, minutos=Decimal(minutos))

    # Las tareas pendientes de esas operaciones toman el tiempo fijo
    for fijo in TiempoFijo.objects.all():
        pendientes = Item.objects.filter(
            operacion_detallada_id=fijo.operacion_id, hecho=False, designacion__cerrada=False,
        )
        for tarea in pendientes:
            tarea.minutos = round(fijo.minutos if fijo.por_pedido else fijo.minutos * tarea.cantidad)
            tarea.save(update_fields=["minutos"])

class Migration(migrations.Migration):

    dependencies = [
        ('designaciones', '0006_maquina_tarifa_hora_operario_tarifa_hora_escalon_and_more'),
    ]

    operations = [migrations.RunPython(llenar, migrations.RunPython.noop)]