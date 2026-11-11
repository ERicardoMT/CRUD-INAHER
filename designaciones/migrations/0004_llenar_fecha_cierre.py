from django.db import migrations

def llenar(apps, schema_editor):
    """Las tareas con ✓ de jornadas ya cerradas toman como fecha de cierre la de su jornada."""
    Item = apps.get_model("designaciones", "ItemDesignacion")
    tareas = Item.objects.filter(hecho=True, designacion__cerrada=True, fecha_cierre__isnull=True)
    for tarea in tareas.select_related("designacion"):
        tarea.fecha_cierre = tarea.designacion.fecha
        tarea.save(update_fields=["fecha_cierre"])


class Migration(migrations.Migration):

    dependencies = [
        ('designaciones', '0003_itemdesignacion_cerrada_al_archivar_and_more'),
    ]

    operations = [migrations.RunPython(llenar, migrations.RunPython.noop)]

