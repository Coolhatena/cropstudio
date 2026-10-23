from base64 import b64encode
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PureWindowsPath
from threading import Event
from typing import BinaryIO, Callable

from PIL import Image
from PySide6.QtCore import QThread, Signal

from models.entities import Crop
from services.images import load_oriented


@dataclass(frozen=True)
class ExportJob:
    source: Path
    crop: Crop
    number: int
    relative_path: Path | None = None


@dataclass
class ExportResult:
    written: list[Path]
    errors: list[str]
    cancelled: bool = False
    destination: Path | None = None


def export_root(project_folder: Path, container: Path) -> Path:
    return (container / f"{project_folder.name or 'Proyecto'}_recortes").resolve()


def job_directory(job: ExportJob, destination: Path) -> Path:
    """Calcula la subcarpeta sin permitir rutas ancladas ni escapes del destino."""
    directory = destination
    if job.relative_path is not None:
        relative = PureWindowsPath(job.relative_path)
        if relative.anchor or ".." in relative.parts or not relative.name:
            raise ValueError("La ruta de la imagen debe ser relativa y permanecer dentro del destino.")
        directory = destination.joinpath(*relative.parts[:-1])
    if not directory.resolve().is_relative_to(destination.resolve()):
        raise ValueError("La carpeta del recorte queda fuera de la raíz de destino.")
    return directory


def save_svg(image: Image.Image, stream: BinaryIO) -> None:
    """Guarda un SVG autónomo con el recorte PNG incrustado y su transparencia."""
    with BytesIO() as png:
        image.save(png, format="PNG")
        payload = b64encode(png.getvalue())
    width, height = image.size
    stream.write((
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" version="1.1" '
        f'width="{width}px" height="{height}px" viewBox="0 0 {width} {height}">\n'
        f'  <image x="0" y="0" width="{width}" height="{height}" '
        'xlink:href="data:image/png;base64,'
    ).encode("utf-8"))
    stream.write(payload)
    stream.write(b'"/>\n</svg>\n')


def unique_file(destination: Path, stem: str, extension: str):
    """Reserva atómicamente el nombre para impedir sobrescrituras."""
    suffix = 0
    while True:
        name = f"{stem}{'_' + str(suffix) if suffix else ''}.{extension}"
        path = destination / name
        try:
            return path, path.open("xb")
        except FileExistsError:
            suffix += 1


def export_jobs(jobs: list[ExportJob], destination: Path, format_name: str, quality: int,
                cancel: Event, progress: Callable[[int, int], None] | None = None) -> ExportResult:
    if format_name not in {"JPG", "PNG", "WEBP", "SVG"} or not 1 <= quality <= 100:
        raise ValueError("Formato o calidad inválidos.")
    result = ExportResult([], [], destination=destination)
    image = None
    current_source = None
    try:
        for index, job in enumerate(jobs, 1):
            if cancel.is_set():
                result.cancelled = True
                break
            reserved = None
            output = None
            try:
                directory = job_directory(job, destination)
                if current_source != job.source:
                    if image is not None:
                        image.close()
                    image = None
                    current_source = None
                    image = load_oriented(job.source)
                    current_source = job.source
                crop = job.crop
                crop.validate(*image.size)
                if not crop.output_matches():
                    raise ValueError("La proporción no coincide con la resolución de salida. Ajuste la geometría.")
                output = image.resize((crop.output_width, crop.output_height), Image.Resampling.LANCZOS, box=crop.box)
                if cancel.is_set():
                    result.cancelled = True
                    break
                if format_name == "JPG":
                    background = Image.new("RGB", output.size, "white")
                    background.paste(output, mask=output.getchannel("A"))
                    output.close()
                    output = background
                directory.mkdir(parents=True, exist_ok=True)
                reserved, stream = unique_file(directory, f"{job.source.stem}_crop_{job.number:02d}", format_name.lower())
                try:
                    with stream:
                        if format_name == "SVG":
                            save_svg(output, stream)
                        else:
                            kwargs = {"quality": quality} if format_name != "PNG" else {}
                            output.save(stream, format="JPEG" if format_name == "JPG" else format_name, **kwargs)
                except Exception:
                    reserved.unlink(missing_ok=True)
                    raise
                result.written.append(reserved)
            except Exception as exc:
                result.errors.append(f"{job.relative_path or job.source.name} / {job.crop.name}: {exc}")
            finally:
                if output is not None:
                    output.close()
            if progress:
                progress(index, len(jobs))
    finally:
        if image is not None:
            image.close()
    return result


class ExportWorker(QThread):
    progress = Signal(int, int)
    completed = Signal(object)

    def __init__(self, jobs: list[ExportJob], destination: Path, format_name: str, quality: int, parent=None):
        super().__init__(parent)
        self.jobs, self.destination, self.format_name, self.quality = jobs, destination, format_name, quality
        self.cancel_event = Event()

    def run(self) -> None:
        try:
            result = export_jobs(self.jobs, self.destination, self.format_name, self.quality,
                                 self.cancel_event, self.progress.emit)
        except Exception as exc:
            result = ExportResult([], [str(exc)], destination=self.destination)
        self.completed.emit(result)
