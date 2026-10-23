from base64 import b64decode
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from threading import Event
from xml.etree import ElementTree as ET

from PIL import Image
import pytest

from models.entities import Template
from services.export import ExportJob, export_jobs, export_root, job_directory
from services.geometry import from_template, template_from_crop
from services.images import load_oriented, scan_images


def open_export(path):
    if path.suffix == ".svg":
        root = ET.parse(path).getroot()
        assert root.tag == "{http://www.w3.org/2000/svg}svg"
        embedded = root.find("{http://www.w3.org/2000/svg}image")
        href = embedded.attrib["{http://www.w3.org/1999/xlink}href"]
        assert href.startswith("data:image/png;base64,")
        image = Image.open(BytesIO(b64decode(href.split(",", 1)[1], validate=True)))
        width, height = image.size
        assert root.attrib["width"] == f"{width}px"
        assert root.attrib["height"] == f"{height}px"
        assert root.attrib["viewBox"] == f"0 0 {width} {height}"
        assert embedded.attrib["width"] == str(width)
        assert embedded.attrib["height"] == str(height)
        return image
    return Image.open(path)


@pytest.mark.parametrize("format_name", ["JPG", "PNG", "WEBP", "SVG"])
def test_exact_exports_and_originals(tmp_path, format_name):
    source = tmp_path / "producto_ñ.png"
    Image.new("RGBA", (83, 61), (255, 0, 0, 120)).save(source)
    original = sha256(source.read_bytes()).digest()
    sizes = [(1000, 1000), (1200, 800), (1920, 1080), (1080, 1920)]
    jobs = [ExportJob(source, from_template(Template(str(n), "t", *size), "i", 83, 61, n), n)
            for n, size in enumerate(sizes, 1)]
    result = export_jobs(jobs, tmp_path / "out", format_name, 90, Event())
    assert not result.errors and len(result.written) == 4
    for path, size in zip(result.written, sizes):
        with open_export(path) as image:
            assert image.size == size
    again = export_jobs(jobs, tmp_path / "out", format_name, 90, Event())
    assert set(again.written).isdisjoint(result.written)
    assert sha256(source.read_bytes()).digest() == original


@pytest.mark.parametrize("format_name", ["PNG", "SVG"])
def test_exif_and_decimal_bounds(tmp_path, format_name):
    path = tmp_path / "rotated.jpg"
    image = Image.new("RGB", (120, 60), "red")
    exif = Image.Exif()
    exif[274] = 6
    image.save(path, exif=exif)
    oriented = load_oriented(path)
    assert oriented.size == (60, 120)
    crop = from_template(Template("t", "Vertical", 30, 60), "i", 60, 120, 1)
    crop.x, crop.y, crop.width, crop.height = 0.25, 0.5, 59.5, 119
    crop = from_template(template_from_crop(crop), "i", *oriented.size, 1)
    result = export_jobs([ExportJob(path, crop, 1)], tmp_path / "out", format_name, 90, Event())
    assert not result.errors
    with open_export(result.written[0]) as exported:
        assert exported.size == (30, 60)


@pytest.mark.parametrize("format_name", ["PNG", "SVG"])
def test_errors_cancellation_and_mismatch(tmp_path, format_name):
    path = tmp_path / "good.png"
    Image.new("RGB", (20, 20)).save(path)
    corrupt = tmp_path / "broken.png"
    corrupt.write_bytes(b"not an image")
    crop = from_template(Template("t", "t", 10, 10), "i", 20, 20, 1)
    jobs = [ExportJob(tmp_path / "missing.jpg", crop, 1), ExportJob(corrupt, crop, 1),
            ExportJob(path, replace(crop, output_width=20), 1), ExportJob(path, crop, 2)]
    result = export_jobs(jobs, tmp_path / "out", format_name, 90, Event())
    assert len(result.errors) == 3 and len(result.written) == 1
    cancel = Event()
    cancel.set()
    result = export_jobs(jobs, tmp_path / "cancel", format_name, 90, cancel)
    assert result.cancelled and not result.written
    cancel.clear()
    result = export_jobs([jobs[-1]] * 10, tmp_path / "partial", format_name, 90, cancel,
                         lambda done, total: cancel.set())
    assert result.cancelled and len(result.written) == 1
    result = export_jobs([jobs[-1], jobs[1], jobs[-1]], tmp_path / "recovery", format_name, 90, Event())
    assert len(result.written) == 2 and len(result.errors) == 1


def test_svg_preserves_crop_pixels_and_transparency_without_source(tmp_path):
    source = tmp_path / "mitades.png"
    image = Image.new("RGBA", (20, 10), (255, 0, 0, 80))
    image.paste((0, 0, 255, 200), (10, 0, 20, 10))
    image.save(source)
    crop = from_template(Template("t", "t", 10, 10), "i", 20, 10, 1)
    crop.x = 10
    result = export_jobs([ExportJob(source, crop, 1)], tmp_path / "out", "SVG", 90, Event())
    assert not result.errors
    source.unlink()
    with open_export(result.written[0]) as exported:
        assert exported.mode == "RGBA"
        assert exported.size == (10, 10)
        assert exported.tobytes() == bytes((0, 0, 255, 200)) * 100


def test_scan_recursive(tmp_path):
    (tmp_path / "ñ").mkdir()
    for name in ["a.JPG", "b.jpeg", "ñ/c.PNG", "d.webp", "no.txt"]:
        (tmp_path / name).touch()
    assert scan_images(tmp_path) == ["a.JPG", "b.jpeg", "d.webp", "ñ/c.PNG"]


@pytest.mark.parametrize("format_name", ["JPG", "PNG", "WEBP", "SVG"])
def test_fixed_template_exports_same_region_on_different_images(tmp_path, format_name):
    template = Template("fixed", "Azul", 20, 20, 20, 10, 10, 10)
    jobs = []
    for number, size in enumerate([(40, 30), (80, 60)], 1):
        source = tmp_path / f"foto_{number}.png"
        image = Image.new("RGBA", size, (255, 0, 0, 255))
        image.paste((0, 0, 255, 120), (10, 0, size[0], size[1]))
        image.save(source)
        jobs.append(ExportJob(source, from_template(template, str(number), *size, 1), 1))
    result = export_jobs(jobs, tmp_path / "fixed", format_name, 90, Event())
    assert not result.errors and len(result.written) == 2
    for path in result.written:
        with open_export(path) as exported:
            assert exported.size == (20, 20)
            if format_name in {"PNG", "SVG"}:
                assert exported.tobytes() == bytes((0, 0, 255, 120)) * 400


@pytest.mark.parametrize("format_name", ["JPG", "PNG", "WEBP", "SVG"])
def test_export_preserves_sports_hierarchy_and_reuses_root(tmp_path, format_name):
    project = tmp_path / "SELECCIONES DEPORTIVAS"
    relatives = [Path("portada.png"), Path("CAMPUS ENSENADA/Fútbol/foto.png"),
                 Path("CAMPUS MEXICALI/NATACIÓN/EQUIPO/foto.png"),
                 Path("CAMPUS MEXICALI/NATACIÓN/INDIVIDUALES/foto.png")]
    jobs = []
    template = Template("t", "Horizontal", 20, 10)
    for index, relative in enumerate(relatives):
        source = project / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (40, 30), (index * 50, 0, 100, 120)).save(source)
        crop = from_template(template, str(index), 40, 30, 1)
        jobs.append(ExportJob(source, crop, 1, relative_path=relative))
    jobs.insert(1, ExportJob(jobs[0].source, jobs[0].crop.duplicate(), 2, relative_path=relatives[0]))
    (project / "CAMPUS ENSENADA/Flag").mkdir()
    without_crops = project / "CAMPUS MEXICALI/BASKET/GRUPAL"
    without_crops.mkdir(parents=True)
    Image.new("RGB", (40, 30)).save(without_crops / "sin_recortes.png")
    (project / "notas.txt").write_text("No se debe copiar", encoding="utf-8")
    hashes = {p.relative_to(project): sha256(p.read_bytes()).digest()
              for p in project.rglob("*") if p.is_file()}
    destination = export_root(project, tmp_path / "Exportaciones")
    assert destination == tmp_path / "Exportaciones/SELECCIONES DEPORTIVAS_recortes"
    assert not destination.exists()
    result = export_jobs(jobs, destination, format_name, 90, Event())
    assert not result.errors and result.destination == destination
    expected = {job.relative_path.parent / f"{job.source.stem}_crop_{job.number:02d}.{format_name.lower()}" for job in jobs}
    assert {path.relative_to(destination) for path in result.written} == expected
    assert {p.relative_to(destination) for p in destination.rglob("*") if p.is_file()} == expected
    assert not (destination / "CAMPUS ENSENADA/Flag").exists()
    assert not (destination / "CAMPUS MEXICALI/BASKET").exists()
    for path in result.written:
        with open_export(path) as exported:
            assert exported.size == (20, 10)
    first_hashes = {path: sha256(path.read_bytes()).digest() for path in result.written}
    repeated = export_jobs(jobs, destination, format_name, 90, Event())
    assert not repeated.errors and len(repeated.written) == len(jobs)
    assert set(repeated.written).isdisjoint(result.written)
    for path in repeated.written:
        assert path.stem.endswith("_1")
    assert first_hashes == {path: sha256(path.read_bytes()).digest() for path in result.written}
    assert hashes == {p.relative_to(project): sha256(p.read_bytes()).digest()
                      for p in project.rglob("*") if p.is_file()}


@pytest.mark.parametrize("relative", ["../escape/foto.png", "campus/../../escape/foto.png",
                                      r"campus\..\foto.png", "/absoluta/foto.png",
                                      r"C:\absoluta\foto.png", "C:foto.png",
                                      r"\\servidor\carpeta\foto.png", "."])
def test_job_rejects_absolute_and_traversal_paths(tmp_path, relative):
    crop = from_template(Template("t", "t", 10, 10), "i", 20, 20, 1)
    job = ExportJob(tmp_path / "foto.png", crop, 1, relative_path=Path(relative))
    destination = tmp_path / "out"
    with pytest.raises(ValueError, match="relativa"):
        job_directory(job, destination)
    assert not destination.exists()


def test_folder_error_does_not_stop_other_branches(tmp_path):
    source = tmp_path / "foto.png"
    Image.new("RGB", (20, 20)).save(source)
    crop = from_template(Template("t", "t", 10, 10), "i", 20, 20, 1)
    destination = tmp_path / "out"
    destination.mkdir()
    blocker = destination / "bloqueada"
    blocker.write_bytes(b"conservar")
    jobs = [ExportJob(source, crop, 1, Path("bloqueada/Equipo/foto.png")),
            ExportJob(source, crop, 1, Path("CAMPUS ENSENADA/Fútbol/foto.png"))]
    progress = []
    result = export_jobs(jobs, destination, "PNG", 90, Event(), lambda done, total: progress.append((done, total)))
    assert len(result.errors) == 1 and "bloqueada" in result.errors[0]
    assert result.written == [destination / "CAMPUS ENSENADA/Fútbol/foto_crop_01.png"]
    assert blocker.read_bytes() == b"conservar"
    assert progress == [(1, 2), (2, 2)]


def test_invalid_crops_and_images_create_no_output_folders(tmp_path):
    source = tmp_path / "foto.png"
    Image.new("RGB", (20, 20)).save(source)
    corrupt = tmp_path / "corrupta.png"
    corrupt.write_bytes(b"no image")
    crop = from_template(Template("t", "t", 10, 10), "i", 20, 20, 1)
    destination = tmp_path / "out"
    jobs = [ExportJob(source, replace(crop, output_width=30), 1, Path("incompatible/foto.png")),
            ExportJob(corrupt, crop, 1, Path("corrupta/foto.png")),
            ExportJob(tmp_path / "ausente.png", crop, 1, Path("ausente/foto.png")),
            ExportJob(source, crop, 1, Path("../escape/foto.png"))]
    result = export_jobs(jobs, destination, "PNG", 90, Event())
    assert not result.written and len(result.errors) == 4
    assert not destination.exists() and not (tmp_path / "escape").exists()


def test_cancel_creates_only_completed_branch(tmp_path):
    source = tmp_path / "foto.png"
    Image.new("RGB", (20, 20)).save(source)
    crop = from_template(Template("t", "t", 10, 10), "i", 20, 20, 1)
    jobs = [ExportJob(source, crop, 1, Path("terminada/foto.png")),
            ExportJob(source, crop, 1, Path("pendiente/foto.png"))]
    destination = tmp_path / "out"
    cancel = Event()
    cancel.set()
    result = export_jobs(jobs, destination, "PNG", 90, cancel)
    assert result.cancelled and not destination.exists()
    cancel.clear()
    result = export_jobs(jobs, destination, "PNG", 90, cancel, lambda done, total: cancel.set())
    assert result.cancelled and len(result.written) == 1
    assert (destination / "terminada/foto_crop_01.png").is_file()
    assert not (destination / "pendiente").exists()
