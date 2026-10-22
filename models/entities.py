from dataclasses import dataclass, replace
from math import gcd, isfinite
from uuid import uuid4


def identifier() -> str:
    return uuid4().hex


def validate_output(name: str, width: int, height: int) -> None:
    if not name.strip():
        raise ValueError("El nombre no puede estar vacío.")
    if type(width) is not int or type(height) is not int or min(width, height) < 1:
        raise ValueError("Las dimensiones deben ser enteros positivos.")


@dataclass(frozen=True)
class Template:
    id: str
    name: str
    width: int
    height: int
    crop_x: float | None = None
    crop_y: float | None = None
    crop_width: float | None = None
    crop_height: float | None = None

    def __post_init__(self) -> None:
        validate_output(self.name, self.width, self.height)
        values = (self.crop_x, self.crop_y, self.crop_width, self.crop_height)
        present = [value is not None for value in values]
        if any(present) and not all(present):
            raise ValueError("La posición y el tamaño deben indicarse completos.")
        if geometry := self.geometry:
            x, y, width, height = geometry
            if not all(isfinite(value) for value in geometry) or min(x, y) < 0 or min(width, height) <= 0:
                raise ValueError("La posición debe ser finita y no negativa, y el tamaño debe ser positivo.")
            if not abs(width / height / (self.width / self.height) - 1) < 1e-5:
                raise ValueError("La proporción del recorte no coincide con la salida. Corrige la geometría antes de guardar la plantilla.")

    @property
    def geometry(self) -> tuple[float, float, float, float] | None:
        if self.crop_x is None or self.crop_y is None or self.crop_width is None or self.crop_height is None:
            return None
        return self.crop_x, self.crop_y, self.crop_width, self.crop_height

    @property
    def ratio(self) -> tuple[int, int]:
        divisor = gcd(self.width, self.height)
        return self.width // divisor, self.height // divisor

    @property
    def label(self) -> str:
        a, b = self.ratio
        mode = "Geometría fija" if self.geometry else "Centrado automático"
        return f"{self.name} · {self.width} × {self.height} ({a}:{b}) · {mode}"


@dataclass(frozen=True)
class Project:
    id: str
    folder: str


@dataclass(frozen=True)
class ImageRecord:
    id: str
    project_id: str
    relative_path: str
    available: bool = True


@dataclass
class Crop:
    id: str
    image_id: str
    name: str
    x: float
    y: float
    width: float
    height: float
    output_width: int
    output_height: int
    ratio_width: float
    ratio_height: float
    locked: bool = True
    template_id: str | None = None

    @property
    def box(self) -> tuple[float, float, float, float]:
        return self.x, self.y, self.x + self.width, self.y + self.height

    def duplicate(self) -> "Crop":
        return replace(self, id=identifier(), name=f"{self.name} copia")

    def validate(self, image_width: int, image_height: int) -> None:
        validate_output(self.name, self.output_width, self.output_height)
        values = (self.x, self.y, self.width, self.height, self.ratio_width, self.ratio_height)
        if not all(isfinite(v) for v in values) or min(self.width, self.height, self.ratio_width, self.ratio_height) <= 0:
            raise ValueError("El recorte debe tener dimensiones y proporción válidas.")
        epsilon = 1e-6
        if self.x < -epsilon or self.y < -epsilon or self.x + self.width > image_width + epsilon or self.y + self.height > image_height + epsilon:
            raise ValueError("El recorte está fuera de la imagen.")

    def output_matches(self) -> bool:
        return abs(self.width / self.height / (self.output_width / self.output_height) - 1) < 1e-5
