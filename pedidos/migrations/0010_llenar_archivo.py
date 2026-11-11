from django.db import migrations

from pedidos.models import armar_busqueda, detectar_modelo

def llenar(apps, schema_editor):
    """Llena el modelo exacto de las partidas y el texto del buscador de los pedidos que ya existen."""
    Partida = apps.get_model("pedidos", "PartidaPedido")
    Pedido = apps.get_model("pedidos", "Pedido")
    for partida in Partida.objects.all():
        partida.modelo = detectar_modelo(partida.descripcion)
        partida.save(update_fields=["modelo"])
    for pedido in Pedido.objects.select_related("cliente"):
        pedido.busqueda = armar_busqueda(pedido)
        pedido.save(update_fields=["busqueda"])


class Migration(migrations.Migration):

    dependencies = [
        ('pedidos', '0009_partidapedido_modelo_pedido_archivado_motivo_and_more'),
    ]

    operations = [migrations.RunPython(llenar, migrations.RunPython.noop)]