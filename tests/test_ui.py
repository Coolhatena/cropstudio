from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from threading import Event

from PIL import Image
import pytest
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox

from models.entities import Template
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
    form.geometry_fields["crop_width"].setValue(1200)
    form.geometry_fields["crop_height"].setValue(800)
    assert form.ratio.text() == "3:2"
    form.name.setText("Mi plantilla")
    form.validate()
    assert form.result() == form.DialogCode.Accepted
    assert form.saved_template.geometry == (0, 0, 1200, 800)
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


def test_save_current_crop_as_template_and_repeat_after_restart(qtbot, tmp_path):
    window, folder = create_window(qtbot, tmp_path)
    assert not window.save_template_button.isEnabled()
    window.add_from_template()
    crop = window.active_crop()
    geometry = (12.123456789012345, 4.987654321098765, 70.12345678901234, 70.12345678901234)
    window.geometry_changed(crop.id, geometry, True)
    before = replace(crop)
    default = window.repository.default_template_id()

    def fill_and_save():
        form = QApplication.activeModalWidget()
        try:
            assert isinstance(form, TemplateForm)
            assert form.name.text() == before.name
            assert form.fixed_geometry.isChecked()
            form.name.setText("Encuadre repetible")
            qtbot.mouseClick(form.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save), Qt.MouseButton.LeftButton)
        finally:
            if form.isVisible():
                form.reject()

    QTimer.singleShot(0, fill_and_save)
    qtbot.mouseClick(window.save_template_button, Qt.MouseButton.LeftButton)
    saved = window.templates[window.template_combo.currentIndex()]
    assert saved.name == "Encuadre repetible" and saved.geometry == geometry
    assert "Geometría fija" in window.template_combo.currentText()
    assert window.repository.default_template_id() == default
    assert window.crops == [before]  # No cambia el recorte ni su referencia de origen.
    assert window.repository.crops(window.current_image.id) == [before]
    # Aplicarla a otra imagen y repetirla en la misma imagen.
    window.image_list.setCurrentRow(1)
    qtbot.mouseClick(window.template_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.template_button, Qt.MouseButton.LeftButton)
    assert len(window.crops) == 2 and window.crops[0].id != window.crops[1].id
    for applied in window.crops:
        assert (applied.x, applied.y, applied.width, applied.height) == geometry
        assert applied.template_id == saved.id and applied.locked
    window.close()
    Image.new("RGB", (320, 240)).save(folder / "mayor.png")
    restored = MainWindow(Repository(tmp_path / "state.sqlite3"))
    qtbot.addWidget(restored)
    restored.show()
    restored.open_folder(folder)
    restored.refresh_templates(saved.id)
    restored.add_from_template()
    applied = restored.active_crop()
    assert restored.current_image.relative_path == "mayor.png"
    assert (applied.x, applied.y, applied.width, applied.height) == geometry
    assert (applied.output_width, applied.output_height) == (1000, 1000)
    assert restored.repository.default_template_id() == default


@pytest.mark.parametrize("geometry", [(0, 0, 200, 200), (155, 0, 10, 10), (0, 115, 10, 10)])
def test_outside_template_popup_creates_nothing(qtbot, tmp_path, monkeypatch, geometry):
    window, _ = create_window(qtbot, tmp_path)
    window.add_from_template()
    before = replace(window.active_crop())
    template = window.repository.add_template(Template("outside", "Fuera", 1000, 1000, *geometry))
    window.refresh_templates(template.id)
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: messages.append(text))
    qtbot.mouseClick(window.template_button, Qt.MouseButton.LeftButton)
    assert messages == ["La plantilla es demasiado grande para la imagen actual"]
    assert window.crops == [before]
    assert window.active_id == before.id and not window.dirty
    assert window.repository.crops(window.current_image.id) == [before]


def test_save_template_cancel_and_mismatch_leave_original_unchanged(qtbot, tmp_path, monkeypatch):
    window, _ = create_window(qtbot, tmp_path)
    window.add_from_template()
    before = replace(window.active_crop())
    templates = window.repository.templates()
    selected = window.template_combo.currentData()
    monkeypatch.setattr(TemplateForm, "exec", lambda form: form.DialogCode.Rejected)
    window.save_crop_as_template()
    assert window.repository.templates() == templates and window.crops == [before]
    assert window.template_combo.currentData() == selected
    window.output_width.setValue(1200)
    invalid = replace(window.active_crop())
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: messages.append(text))
    window.save_crop_as_template()
    assert len(messages) == 1 and "Corrige la geometría" in messages[0]
    assert window.crops == [invalid] and window.repository.templates() == templates


def test_form_precision_editing_and_saving_failure_recovery(qtbot, repository, monkeypatch):
    base = Template("precision", "Exacta", 1200, 800, 1.12345678901234, 2.98765432109876,
                    120.1234567890123, 80.0823045260082)
    attempts = 0

    def save(candidate):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("Disco lleno")
        return repository.add_template(candidate)

    form = TemplateForm(base, on_save=save)
    qtbot.addWidget(form)
    form.show()
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda parent, title, text: errors.append(text))
    form.validate()
    assert errors == ["Disco lleno"] and form.isVisible()
    assert form.name.text() == base.name and form.saved_template is None
    form.validate()
    assert form.result() == form.DialogCode.Accepted
    assert form.saved_template == base and base in repository.templates()
    edit = TemplateForm(base, on_save=repository.update_template)
    qtbot.addWidget(edit)
    edit.geometry_fields["crop_x"].setValue(12.5)
    edit.validate()
    expected = replace(base, crop_x=12.5)
    assert edit.saved_template == expected and expected in repository.templates()


def test_template_form_legacy_mode_and_validation(qtbot, repository, monkeypatch):
    base = repository.templates()[0]
    form = TemplateForm(base, on_save=repository.update_template)
    qtbot.addWidget(form)
    assert not form.fixed_geometry.isChecked() and not form.geometry_widget.isEnabled()
    form.name.setText("Antigua renombrada")
    form.validate()
    assert form.saved_template.geometry is None
    fixed = TemplateForm(form.saved_template, on_save=repository.update_template)
    qtbot.addWidget(fixed)
    fixed.fixed_geometry.setChecked(True)
    fixed.geometry_fields["crop_x"].setValue(15)
    fixed.geometry_fields["crop_y"].setValue(25)
    fixed.geometry_fields["crop_width"].setValue(60)
    fixed.geometry_fields["crop_height"].setValue(40)
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: errors.append(text))
    fixed.validate()
    assert len(errors) == 1 and fixed.saved_template is None
    assert next(t for t in repository.templates() if t.id == base.id).geometry is None
    fixed.geometry_fields["crop_height"].setValue(60)
    fixed.validate()
    assert fixed.saved_template.geometry == (15, 25, 60, 60)
    centered = TemplateForm(fixed.saved_template, on_save=repository.update_template)
    qtbot.addWidget(centered)
    centered.fixed_geometry.setChecked(False)
    centered.validate()
    assert centered.saved_template.geometry is None


def test_first_template_saved_from_crop_becomes_default(qtbot, tmp_path, monkeypatch):
    window, _ = create_window(qtbot, tmp_path)
    for template in window.repository.templates():
        window.repository.delete_template(template.id)
    window.refresh_templates()
    window.manual_crop((10, 10, 60, 60))
    source = replace(window.active_crop())

    def save(form):
        form.validate()
        return form.result()

    monkeypatch.setattr(TemplateForm, "exec", save)
    window.save_crop_as_template()
    assert window.template_combo.count() == 1
    assert window.repository.default_template_id() == window.template_combo.currentData()
    assert window.crops == [source]


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
