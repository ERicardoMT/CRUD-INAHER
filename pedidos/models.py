from django.db import models


class Pedido(models.Model):

    class Estado(models.TextChoices):
        DETENIDO = "DETENIDO", "Detenido"
        EN_PROCESO = "EN_PROCESO", "En proceso"
        TERMINADO = "TERMINADO", "Terminado"
        ENTREGADO = "ENTREGADO", "Entregado"

    # Estados que ya no cuentan como pedido abierto
    ESTADOS_CERRADOS = ["TERMINADO", "ENTREGADO"]

    numero = models.CharField(
        max_length=30,
        unique=True,
        verbose_name="Número de pedido",
    )

    descripcion = models.TextField(
        verbose_name="Descripción del producto",
    )

    cantidad = models.PositiveIntegerField(
        default=1,
        verbose_name="Cantidad total",
    )

    fecha_salida = models.DateField(
        verbose_name="Fecha de salida",
        blank=True,
        null=True,
    )

    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.EN_PROCESO,
        verbose_name="Estado del pedido",
    )

    detenido_por = models.CharField(
        max_length=150,
        blank=True,
        default="",
        verbose_name="Detenido por",
        help_text="Motivo de la detención, ej. 'Base MT-2 · llega 12 nov'",
    )

    notas = models.TextField(
        blank=True,
        verbose_name="Notas u observaciones",
    )

    fecha_creacion = models.DateTimeField(
        auto_now_add=True,
    )

    fecha_actualizacion = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["-fecha_creacion"]
        verbose_name = "Pedido"
        verbose_name_plural = "Pedidos"

    @property
    def dias_restantes(self):
        """Calcula Días = Fecha salida - HOY()"""
        if not self.fecha_salida:
            return None
        from django.utils import timezone
        return (self.fecha_salida - timezone.localdate()).days

    @property
    def alerta_estado(self):
        """Replica la fórmula exacta de la columna Estado del Excel"""
        if self.estado == self.Estado.ENTREGADO:
            return {"texto": "ENTREGADO", "clase": "status-terminado"}
        if self.estado == self.Estado.TERMINADO:
            return {"texto": "LISTO", "clase": "status-terminado"}
        
        dias = self.dias_restantes
        if dias is None:
            return {"texto": "SIN FECHA", "clase": "status-neutral"}
        
        if dias < 0:
            return {"texto": f"ATRASADO {abs(dias)} d", "dias": dias, "clase": "status-detenido"}
        elif dias == 0:
            return {"texto": "SALE HOY", "dias": 0, "clase": "status-proceso"}
        elif dias <= 2:
            return {"texto": "URGENTE", "dias": dias, "clase": "status-proceso"}
        else:
            return {"texto": "EN TIEMPO", "dias": dias, "clase": "status-terminado"}

    def __str__(self):
        return f"Pedido {self.numero}"