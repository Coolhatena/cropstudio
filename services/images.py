from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageOps
from PySide6.QtGui import QImage


EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def scan_images(folder: Path) -> list[str]:
    return sorted((p.relative_to(folder).as_posix() for p in folder.rglob("*")
                   if p.is_file() and p.suffix.lower() in EXTENSIONS), key=str.casefold)


def load_oriented(path: Path) -> Image.Image:
    with Image.open(path) as source:
        return ImageOps.exif_transpose(source).convert("RGBA")


def to_qimage(image: Image.Image) -> QImage:
    rgba = image.convert("RGBA")
    return QImage(rgba.tobytes(), rgba.width, rgba.height, rgba.width * 4,
                  QImage.Format.Format_RGBA8888).copy()


@lru_cache(maxsize=128)
def thumbnail(path: str, modified: int) -> QImage:
    """La fecha invalida la caché cuando cambia un archivo."""
    with Image.open(path) as source:
        source.draft("RGB", (160, 160))
        image = ImageOps.exif_transpose(source)
        image.thumbnail((96, 72))
        return to_qimage(image)
