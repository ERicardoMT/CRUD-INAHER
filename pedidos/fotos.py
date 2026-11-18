"""Fotos subidas desde el celular: se reducen a 1,600 px por lado y se guardan como JPEG."""
from io import BytesIO
from pathlib import Path

from django.core.files.uploadedfile import InMemoryUploadedFile
from PIL import Image, ImageOps

LADO_MAYOR = 1600


def comprimir_foto(archivo, lado_mayor=LADO_MAYOR, calidad=80):
    imagen = ImageOps.exif_transpose(Image.open(archivo))  # respeta la orientación del celular
    imagen.thumbnail((lado_mayor, lado_mayor))
    if imagen.mode not in ("RGB", "L"):
        imagen = imagen.convert("RGB")
    salida = BytesIO()
    imagen.save(salida, "JPEG", quality=calidad, optimize=True)  # sin EXIF: no guarda la ubicación GPS
    tamano = salida.tell()
    salida.seek(0)
    return InMemoryUploadedFile(salida, "acuse", f"{Path(archivo.name).stem}.jpg", "image/jpeg", tamano, None)
