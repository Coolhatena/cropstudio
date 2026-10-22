from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from threading import Event

from PIL import Image
import pytest
from PySide6.QtCore import QPointF, Qt

from services.export import ExportJob, ExportWorker, export_jobs
from storage.repository import Repository
from ui.dialogs import ExportOptions, TemplateForm, TemplateManager
from ui.window import MainWindow


def create_window(qtbot, tmp_path, count=2):
    folder = tmp_path / "imágenes"
    folder.mkdir(exist_ok=True)
    for n in range(count):
        Image.new("RGB", (160, 120), (n % 255, 80, 120)).save(folder / f"producto_{n:03}.png")
    window = MainWindow(Repository(tmp_path / "state.sqlite3"))
    qtbot.addWidget(window)
    window.show()
    window.open_folder(folder)
    qtbot.waitUntil(lambda: window.pil_image is not None)
    return window, folder


def test_template_selector_and_snapshot(qtbot, tmp_path):
    window, folder = create_window(qtbot, tmp_path)
    assert window.template_combo.count() == 4
    assert window.template_combo.currentData() == window.repository.default_template_id()
    qtbot.mouseClick(window.template_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.template_button, Qt.MouseButton.LeftButton)
    assert len(window.crops) == 2
    assert window.crops[0].id != window.crops[1].id
    before = replace(window.crops[0])
    window.template_combo.setCurrentIndex(2)
    assert window.crops[0] == before
    qtbot.mouseClick(window.template_button, Qt.MouseButton.LeftButton)
    assert window.crops[-1].output_width == 1920
    template = window.templates[0]
    window.repository.update_template(replace(template, width=99, height=33))
    window.repository.delete_template(template.id)
    window.refresh_templates()
    assert window.repository.crops(window.current_image.id)[0] == replace(before, template_id=None)
    window.image_list.setCurrentRow(1)
    qtbot.mouseClick(window.template_button, Qt.MouseButton.LeftButton)
    assert len(window.crops) == 1


def test_numeric_geometry_drag_and_view_transform(qtbot, tmp_path):
    window, _ = create_window(qtbot, tmp_path)
    window.add_from_template()
    window.geometry_fields["width"].setValue(60)
    crop = window.active_crop()
    assert crop.width == pytest.approx(60) and crop.height == pytest.approx(60)
    # Los pasos de las flechas se reflejan sin esperar a abandonar el campo.
    window.geometry_fields["width"].stepUp()
    assert crop.width == pytest.approx(61) and crop.height == pytest.approx(61)
    editor = window.editor
    editor.fit_image()
    point = QPointF(25, 40)
    back = editor.mapToScene(editor.mapFromScene(point))
    assert abs(back.x()-point.x()) < 1/editor.transform().m11()
    editor.scale(2, 2)
    back = editor.mapToScene(editor.mapFromScene(point))
    assert abs(back.y()-point.y()) < 1/editor.transform().m11()
    editor.fit_image()
    old_x, old_y = crop.x, crop.y
    center = editor.mapFromScene(QPointF(crop.x+crop.width/2, crop.y+crop.height/2))
    target = editor.mapFromScene(QPointF(crop.x+crop.width/2+10, crop.y+crop.height/2+10))
    qtbot.mousePress(editor.viewport(), Qt.MouseButton.LeftButton, pos=center)
    qtbot.mouseMove(editor.viewport(), target)
    qtbot.mouseRelease(editor.viewport(), Qt.MouseButton.LeftButton, pos=target)
    assert crop.x > old_x and crop.y > old_y
    corner = editor.mapFromScene(QPointF(crop.x+crop.width, crop.y+crop.height))
    target = editor.mapFromScene(QPointF(crop.x+crop.width+10, crop.y+crop.height+10))
    qtbot.mousePress(editor.viewport(), Qt.MouseButton.LeftButton, pos=corner)
    qtbot.mouseMove(editor.viewport(), target)
    qtbot.mouseRelease(editor.viewport(), Qt.MouseButton.LeftButton, pos=target)
    assert crop.width == pytest.approx(crop.height)
    crop.validate(160, 120)
    assert window.repository.crops(window.current_image.id)[0].width == pytest.approx(crop.width)


def test_write_failure_retains_pending_and_retries(qtbot, tmp_path, monkeypatch):
    window, _ = create_window(qtbot, tmp_path)
    save = window.repository.save_crops

    def fail(*args):
        raise OSError("Disco lleno")

    monkeypatch.setattr(window.repository, "save_crops", fail)
    window.add_from_template()
    assert window.dirty and not window.retry_button.isHidden()
    old = window.current_image.id
    window.image_list.setCurrentRow(1)
    assert window.current_image.id == old and len(window.crops) == 1
    monkeypatch.setattr(window.repository, "save_crops", save)
    qtbot.mouseClick(window.retry_button, Qt.MouseButton.LeftButton)
    assert not window.dirty
    window.image_list.setCurrentRow(1)
    window.image_list.setCurrentRow(0)
    assert len(window.crops) == 1


def test_template_form_and_manager(qtbot, repository):
    form = TemplateForm()
    qtbot.addWidget(form)
    form.width.setValue(1200)
    form.height.setValue(800)
    assert form.ratio.text() == "3:2"
    form.name.setText("Mi plantilla")
    form.validate()
    assert form.result() == form.DialogCode.Accepted
    template = repository.create_template(form.name.text(), form.width.value(), form.height.value())
    manager = TemplateManager(repository)
    qtbot.addWidget(manager)
    manager.refresh(template.id)
    manager.duplicate()
    assert manager.selected().name == "Mi plantilla copia"
    manager.make_default()
    assert repository.default_template_id() == manager.selected().id


def test_svg_export_option_and_quality(qtbot):
    dialog = ExportOptions()
    qtbot.addWidget(dialog)
    dialog.format.setCurrentText("SVG")
    assert dialog.format.currentText() == "SVG"
    assert not dialog.quality.isEnabled()
    assert not dialog.svg_note.isHidden()
    dialog.format.setCurrentText("JPG")
    assert dialog.quality.isEnabled() and dialog.svg_note.isHidden()
    dialog.format.setCurrentText("PNG")
    assert not dialog.quality.isEnabled()
    dialog.format.setCurrentText("WEBP")
    assert dialog.quality.isEnabled()


def test_export_worker_completes_through_qt_signals(qtbot, tmp_path):
    window, folder = create_window(qtbot, tmp_path)
    window.add_from_template()
    job = ExportJob(folder / window.current_image.relative_path, replace(window.crops[0]), 1)
    worker = ExportWorker([job], tmp_path / "background", "PNG", 95)
    with qtbot.waitSignal(worker.completed, timeout=15000) as signal:
        worker.start()
    worker.wait(15000)
    result = signal.args[0]
    assert not result.errors and len(result.written) == 1


def test_manual_crop_mismatch_and_explicit_correction(qtbot, tmp_path):
    window, _ = create_window(qtbot, tmp_path)
    window.start_draw()
    editor = window.editor
    a, b = editor.mapFromScene(QPointF(10, 10)), editor.mapFromScene(QPointF(75, 65))
    qtbot.mousePress(editor.viewport(), Qt.MouseButton.LeftButton, pos=a)
    qtbot.mouseMove(editor.viewport(), b)
    qtbot.mouseRelease(editor.viewport(), Qt.MouseButton.LeftButton, pos=b)
    assert len(window.crops) == 1 and window.crops[0].output_matches()
    window.output_width.setValue(1080)
    window.output_height.setValue(1920)
    assert not window.active_crop().output_matches()
    window.correct_ratio()
    assert window.active_crop().output_matches()


def test_100_images_restart_export_and_unchanged_originals(qtbot, tmp_path):
    window, folder = create_window(qtbot, tmp_path, 100)
    hashes = {p.name: sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
    for index in (0, 1):
        window.image_list.setCurrentRow(index)
        for template in (0, 1, 3):
            window.template_combo.setCurrentIndex(template)
            window.add_from_template()
    snapshots = {record.id: window.repository.crops(record.id) for record in window.images}
    window.close()
    restored = MainWindow(Repository(tmp_path / "state.sqlite3"))
    qtbot.addWidget(restored)
    restored.show()
    restored.open_folder(folder)
    assert len(restored.images) == 100
    for record in restored.images:
        assert restored.repository.crops(record.id) == snapshots[record.id]
    restored.geometry_fields["width"].setValue(60)
    restored.apply_fields("width")
    jobs = [ExportJob(folder / record.relative_path, crop, n)
            for record in restored.images
            for n, crop in enumerate(restored.repository.crops(record.id), 1)]
    result = export_jobs(jobs, tmp_path / "exportados", "JPG", 90, Event())
    assert not result.errors and len(result.written) == 6
    for path, job in zip(result.written, jobs):
        with Image.open(path) as exported:
            assert exported.size == (job.crop.output_width, job.crop.output_height)
    assert hashes == {p.name: sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
    # Captura reproducible para inspección del editor real.
    capture = Path(__file__).resolve().parents[1] / "build" / "ui-preview.png"
    capture.parent.mkdir(exist_ok=True)
    qtbot.wait(100)
    restored.grab().save(str(capture))
