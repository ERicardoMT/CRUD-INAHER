from django.db import models


class Pedido(models.Model):

    class Estado(models.TextChoices):
        DETENIDO = "DETENIDO", "Detenido"
        EN_PROCESO = "EN_PROCESO", "En proceso"
        TERMINADO = "TERMINADO", "Terminado"

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

    def __str__(self):
        return f"Pedido {self.numero}"