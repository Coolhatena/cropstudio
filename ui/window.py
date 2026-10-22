from dataclasses import replace
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QIcon, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                              QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                              QMainWindow, QMessageBox, QProgressDialog, QPushButton, QScrollArea,
                              QSpinBox, QSplitter, QVBoxLayout, QWidget)

from models.entities import Crop, ImageRecord, Project, identifier
from services.export import ExportJob, ExportResult, ExportWorker
from services.geometry import fit_rect, from_template
from services.images import load_oriented, scan_images, thumbnail, to_qimage
from storage.repository import Repository
from ui.dialogs import ExportOptions, TemplateManager
from ui.editor import CropEditor


STYLE = """
QWidget { background: #20252d; color: #e8edf4; font-family: 'Segoe UI'; font-size: 13px; }
QMainWindow, QSplitter { background: #15181d; }
QPushButton { background: #343e4c; border: 1px solid #485568; border-radius: 5px; padding: 7px 10px; }
QPushButton:hover { background: #465469; }
QPushButton:disabled { color: #687383; background: #282f39; }
QPushButton#primary { background: #237d6e; border-color: #52dcc2; font-weight: 600; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: #151b23; padding: 5px; border: 1px solid #465264; border-radius: 3px; }
QListWidget { background: #191e26; border: 1px solid #343e4c; border-radius: 4px; }
QListWidget::item { padding: 6px; }
QListWidget::item:selected { background: #27594f; }
QLabel#heading { font-size: 17px; font-weight: 600; padding: 5px 0; color: #52dcc2; }
QSplitter::handle { background: #11151b; width: 5px; }
QScrollArea { border: 0; }
QToolTip { background: #343e4c; color: white; }
"""


def button(text: str, callback, primary: bool = False) -> QPushButton:
    result = QPushButton(text)
    if primary:
        result.setObjectName("primary")
    result.clicked.connect(callback)
    return result


def heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("heading")
    return label


class MainWindow(QMainWindow):
    def __init__(self, repository: Repository | None = None):
        super().__init__()
        self.repository = repository or Repository()
        self.project: Project | None = None
        self.images: list[ImageRecord] = []
        self.current_image: ImageRecord | None = None
        self.pil_image: Image.Image | None = None
        self.crops: list[Crop] = []
        self.active_id: str | None = None
        self.dirty = False
        self.updating = False
        self.worker: ExportWorker | None = None
        self.settings = QSettings("CropStudio", "CropStudio")
        self.setWindowTitle("Crop Studio")
        self.resize(1450, 900)
        self.setStyleSheet(STYLE)
        splitter = QSplitter()
        self.setCentralWidget(splitter)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(heading("Crop Studio"))
        left_layout.addWidget(button("Seleccionar carpeta", self.choose_folder))
        left_layout.addWidget(button("Actualizar carpeta", self.refresh_project))
        self.folder_label = QLabel("Selecciona una carpeta para empezar")
        self.folder_label.setWordWrap(True)
        left_layout.addWidget(self.folder_label)
        self.count_label = QLabel("Sin proyecto")
        self.count_label.setWordWrap(True)
        left_layout.addWidget(self.count_label)
        self.image_list = QListWidget()
        self.image_list.setIconSize(QSize(72, 54))
        self.image_list.currentRowChanged.connect(self.image_selected)
        left_layout.addWidget(self.image_list)
        splitter.addWidget(left)
        center = QWidget()
        center_layout = QVBoxLayout(center)
        tools = QHBoxLayout()
        tools.addWidget(button("Ajustar a ventana", lambda: self.editor.fit_image()))
        self.draw_button = button("Dibujar recorte", self.start_draw)
        tools.addWidget(self.draw_button)
        tools.addStretch()
        center_layout.addLayout(tools)
        self.editor = CropEditor()
        self.editor.selected.connect(self.select_crop)
        self.editor.geometry_changed.connect(self.geometry_changed)
        self.editor.drawn.connect(self.manual_crop)
        center_layout.addWidget(self.editor, 1)
        help_label = QLabel("Rueda: zoom · Botón central o Ctrl+arrastrar: desplazar · Lista derecha: seleccionar recortes superpuestos")
        help_label.setWordWrap(True)
        center_layout.addWidget(help_label)
        splitter.addWidget(center)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        right = QWidget()
        right.setMinimumWidth(305)
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(heading("Plantillas"))
        self.template_combo = QComboBox()
        self.template_combo.setMinimumContentsLength(20)
        self.template_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.template_combo.currentIndexChanged.connect(self.update_actions)
        right_layout.addWidget(self.template_combo)
        self.template_button = button("Nuevo recorte desde plantilla", self.add_from_template, True)
        right_layout.addWidget(self.template_button)
        right_layout.addWidget(button("Gestionar plantillas…", self.manage_templates))
        right_layout.addWidget(heading("Recortes de la imagen"))
        self.crop_list = QListWidget()
        self.crop_list.setMinimumHeight(110)
        self.crop_list.setMaximumHeight(190)
        self.crop_list.currentRowChanged.connect(self.crop_selected)
        right_layout.addWidget(self.crop_list)
        row = QHBoxLayout()
        self.duplicate_button = button("Duplicar", self.duplicate_crop)
        self.delete_button = button("Eliminar", self.delete_crop)
        row.addWidget(self.duplicate_button)
        row.addWidget(self.delete_button)
        right_layout.addLayout(row)
        self.fields_widget = QWidget()
        form = QFormLayout(self.fields_widget)
        form.setContentsMargins(0, 0, 0, 0)
        self.name_edit = QLineEdit()
        self.name_edit.editingFinished.connect(self.apply_fields)
        form.addRow("Nombre", self.name_edit)
        self.geometry_fields: dict[str, QDoubleSpinBox] = {}
        for key, label in [("x", "X"), ("y", "Y"), ("width", "Ancho original"), ("height", "Alto original")]:
            field = QDoubleSpinBox()
            field.setDecimals(4)
            field.setRange(0 if key in {"x", "y"} else 0.0001, 1000000)
            field.setKeyboardTracking(False)
            field.valueChanged.connect(lambda _value, key=key: self.apply_fields(key))
            self.geometry_fields[key] = field
            form.addRow(label, field)
        self.output_width, self.output_height = QSpinBox(), QSpinBox()
        for field in (self.output_width, self.output_height):
            field.setRange(1, 100000)
            field.setKeyboardTracking(False)
            field.valueChanged.connect(lambda _value: self.apply_fields())
        form.addRow("Salida: ancho (px)", self.output_width)
        form.addRow("Salida: alto (px)", self.output_height)
        self.ratio_combo = QComboBox()
        for text, value in [("Personalizada", None), ("1:1", (1, 1)), ("4:3", (4, 3)), ("3:2", (3, 2)), ("16:9", (16, 9)), ("9:16", (9, 16))]:
            self.ratio_combo.addItem(text, value)
        self.ratio_combo.currentIndexChanged.connect(self.ratio_changed)
        form.addRow("Proporción", self.ratio_combo)
        self.ratio_width, self.ratio_height = QDoubleSpinBox(), QDoubleSpinBox()
        ratio_row = QHBoxLayout()
        for field in (self.ratio_width, self.ratio_height):
            field.setRange(0.0001, 1000000)
            field.setDecimals(4)
            field.setKeyboardTracking(False)
            field.valueChanged.connect(self.custom_ratio_changed)
            ratio_row.addWidget(field)
        form.addRow(QLabel("Relación personalizada: ancho : alto"))
        form.addRow(ratio_row)
        self.locked = QCheckBox("Bloquear proporción")
        self.locked.clicked.connect(self.lock_changed)
        form.addRow(self.locked)
        self.mismatch = QLabel()
        self.mismatch.setWordWrap(True)
        form.addRow(self.mismatch)
        form.addRow(button("Ajustar a resolución de salida", self.correct_ratio))
        right_layout.addWidget(self.fields_widget)
        self.preview = QLabel("Vista previa")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(130)
        right_layout.addWidget(self.preview)
        right_layout.addStretch()
        self.export_button = button("Exportar todos…", self.start_export, True)
        scroll.setWidget(right)
        right_shell = QWidget()
        right_shell_layout = QVBoxLayout(right_shell)
        right_shell_layout.setContentsMargins(0, 0, 0, 0)
        right_shell_layout.addWidget(scroll, 1)
        right_shell_layout.addWidget(self.export_button)
        splitter.addWidget(right_shell)
        splitter.setSizes([250, 850, 350])
        self.retry_button = button("Reintentar guardado", self.persist)
        self.statusBar().addPermanentWidget(self.retry_button)
        self.retry_button.hide()
        self.thumb_timer = QTimer(self)
        self.thumb_timer.timeout.connect(self.next_thumbnail)
        self.thumb_index = 0
        self.refresh_templates()
        self.refresh_crops()
        self.statusBar().showMessage("Listo. Los originales nunca se modifican.")

    def update_actions(self, *_args) -> None:
        valid = self.pil_image is not None
        self.template_button.setEnabled(valid and self.template_combo.currentIndex() >= 0)
        self.draw_button.setEnabled(valid)
        self.export_button.setEnabled(self.project is not None and not (self.worker and self.worker.isRunning()))
        active = self.active_crop() is not None
        self.fields_widget.setEnabled(active and valid)
        self.duplicate_button.setEnabled(active)
        self.delete_button.setEnabled(active)

    def refresh_templates(self) -> None:
        self.templates = self.repository.templates()
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        default = self.repository.default_template_id()
        for index, template in enumerate(self.templates):
            self.template_combo.addItem(template.label, template.id)
            if template.id == default:
                self.template_combo.setCurrentIndex(index)
        self.template_combo.blockSignals(False)
        self.update_actions()

    def manage_templates(self) -> None:
        if not self.persist():
            return
        TemplateManager(self.repository, self).exec()
        valid_ids = {t.id for t in self.repository.templates()}
        for crop in self.crops:
            if crop.template_id not in valid_ids:
                crop.template_id = None
        self.refresh_templates()

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Carpeta de imágenes", self.settings.value("folder", ""))
        if folder:
            self.open_folder(Path(folder))

    def open_folder(self, folder: Path) -> None:
        if not self.persist():
            return
        try:
            if not folder.is_dir():
                raise ValueError("La carpeta no está disponible.")
            paths = scan_images(folder)
            project = self.repository.open_project(folder)
            images = self.repository.sync_images(project, paths)
        except Exception as exc:
            QMessageBox.critical(self, "No se pudo abrir el proyecto", str(exc))
            return
        self.thumb_timer.stop()
        self.project, self.images = project, images
        self.current_image = None
        self.crops = []
        self.active_id = None
        self.image_list.blockSignals(True)
        self.image_list.clear()
        for image in self.images:
            item = QListWidgetItem(image.relative_path)
            item.setToolTip(image.relative_path)
            self.image_list.addItem(item)
        self.image_list.blockSignals(False)
        self.folder_label.setText(str(folder))
        self.settings.setValue("folder", str(folder))
        self.clear_image()
        self.update_counts()
        if self.images:
            self.image_list.setCurrentRow(0)
        self.thumb_index = 0
        self.thumb_timer.start(15)

    def refresh_project(self) -> None:
        if self.project:
            self.open_folder(Path(self.project.folder))

    def next_thumbnail(self) -> None:
        if self.thumb_index >= len(self.images) or not self.project:
            self.thumb_timer.stop()
            return
        index = self.thumb_index
        self.thumb_index += 1
        record = self.images[index]
        if not record.available:
            return
        path = Path(self.project.folder) / record.relative_path
        try:
            thumb = thumbnail(str(path), path.stat().st_mtime_ns)
            self.image_list.item(index).setIcon(QIcon(QPixmap.fromImage(thumb)))
        except Exception:
            self.image_list.item(index).setToolTip(record.relative_path + "\nNo se pudo generar la miniatura.")

    def clear_image(self) -> None:
        if self.pil_image is not None:
            self.pil_image.close()
        self.pil_image = None
        self.editor.set_image(None)
        self.refresh_crops()

    def image_selected(self, index: int) -> None:
        if index < 0:
            return
        if not self.persist():
            previous = next((i for i, image in enumerate(self.images) if self.current_image and image.id == self.current_image.id), -1)
            self.image_list.blockSignals(True)
            self.image_list.setCurrentRow(previous)
            self.image_list.blockSignals(False)
            return
        record = self.images[index]
        try:
            crops = self.repository.crops(record.id)
        except Exception as exc:
            QMessageBox.critical(self, "No se pudieron leer los recortes", str(exc))
            return
        self.clear_image()
        self.current_image = record
        self.crops = crops
        self.active_id = self.crops[0].id if self.crops else None
        try:
            self.pil_image = load_oriented(Path(self.project.folder) / record.relative_path)
            self.editor.set_image(to_qimage(self.pil_image))
            self.statusBar().showMessage(f"{record.relative_path} · {self.pil_image.width} × {self.pil_image.height} px")
        except Exception as exc:
            self.statusBar().showMessage(f"Imagen no disponible: {record.relative_path} · {exc}")
        self.refresh_crops()

    def active_crop(self) -> Crop | None:
        return next((c for c in self.crops if c.id == self.active_id), None)

    def refresh_crops(self) -> None:
        self.crop_list.blockSignals(True)
        self.crop_list.clear()
        for index, crop in enumerate(self.crops):
            self.crop_list.addItem(f"{crop.name} · {crop.output_width} × {crop.output_height}")
            if crop.id == self.active_id:
                self.crop_list.setCurrentRow(index)
        self.crop_list.blockSignals(False)
        self.editor.set_crops(self.crops if self.pil_image else [], self.active_id)
        self.populate_fields()
        self.update_actions()

    def crop_selected(self, index: int) -> None:
        if index >= 0:
            self.select_crop(self.crops[index].id)

    def select_crop(self, crop_id: str) -> None:
        self.active_id = crop_id
        self.refresh_crops()

    def populate_fields(self) -> None:
        crop = self.active_crop()
        self.updating = True
        try:
            if crop:
                self.name_edit.setText(crop.name)
                for key, field in self.geometry_fields.items():
                    field.setValue(getattr(crop, key))
                self.output_width.setValue(crop.output_width)
                self.output_height.setValue(crop.output_height)
                self.locked.setChecked(bool(crop.locked))
                self.ratio_width.setValue(crop.ratio_width)
                self.ratio_height.setValue(crop.ratio_height)
                index = 0
                for i in range(1, self.ratio_combo.count()):
                    a, b = self.ratio_combo.itemData(i)
                    if abs(a/b - crop.ratio_width/crop.ratio_height) < 1e-8:
                        index = i
                self.ratio_combo.setCurrentIndex(index)
                self.mismatch.setText("" if crop.output_matches() else "⚠ Proporción incompatible con la salida. Ajusta la geometría antes de exportar.")
                self.update_preview()
            else:
                self.preview.clear()
        finally:
            self.updating = False

    def update_preview(self) -> None:
        crop = self.active_crop()
        if crop and self.pil_image:
            try:
                crop.validate(*self.pil_image.size)
                scale = min(240/crop.width, 140/crop.height)
                size = max(1, round(crop.width*scale)), max(1, round(crop.height*scale))
                preview = self.pil_image.resize(size, Image.Resampling.BILINEAR, box=crop.box)
                self.preview.setPixmap(QPixmap.fromImage(to_qimage(preview)))
                preview.close()
            except ValueError:
                self.preview.setText("Recorte fuera de límites. Ajusta su geometría.")
        else:
            self.preview.setText("Vista previa no disponible")

    def changed(self) -> None:
        self.dirty = True
        self.persist()
        self.refresh_crops()

    def persist(self) -> bool:
        if not self.dirty or not self.current_image:
            return True
        try:
            self.repository.save_crops(self.current_image.id, self.crops)
        except Exception as exc:
            self.retry_button.show()
            self.statusBar().showMessage(f"Cambios pendientes sin guardar: {exc}. Reintenta antes de continuar.")
            return False
        self.dirty = False
        self.retry_button.hide()
        self.statusBar().showMessage("Cambios guardados")
        self.update_counts()
        return True

    def update_counts(self) -> None:
        if not self.project:
            return
        counts = self.repository.crop_counts(self.project.id)
        configured = 0
        for index, record in enumerate(self.images):
            count = counts.get(record.id, 0)
            configured += bool(count)
            self.image_list.item(index).setText(f"{record.relative_path}\n{count} recortes" + (" · Ausente" if not record.available else ""))
        missing = sum(not i.available for i in self.images)
        self.count_label.setText(f"{len(self.images)} imágenes · {configured} configuradas\n{len(self.images)-configured} pendientes · {missing} ausentes")

    def add_crop(self, crop: Crop) -> None:
        self.crops.append(crop)
        self.active_id = crop.id
        self.changed()

    def add_from_template(self) -> None:
        index = self.template_combo.currentIndex()
        if self.pil_image and self.current_image and index >= 0:
            self.add_crop(from_template(self.templates[index], self.current_image.id, *self.pil_image.size, len(self.crops)+1))

    def start_draw(self) -> None:
        if self.pil_image:
            self.editor.drawing = True
            self.editor.setCursor(Qt.CursorShape.CrossCursor)
            self.statusBar().showMessage("Arrastra sobre la imagen para crear un recorte libre.")

    def manual_crop(self, values) -> None:
        if not self.current_image:
            return
        x, y, w, h = values
        ow, oh = max(1, round(w)), max(1, round(h))
        x, y, w, h = fit_rect(x, y, w, h, *self.pil_image.size, ow / oh)
        self.add_crop(Crop(identifier(), self.current_image.id, f"Recorte {len(self.crops)+1}", x, y, w, h,
                           ow, oh, ow, oh, False))

    def duplicate_crop(self) -> None:
        if crop := self.active_crop():
            self.add_crop(crop.duplicate())

    def delete_crop(self) -> None:
        if crop := self.active_crop():
            self.crops.remove(crop)
            self.active_id = self.crops[0].id if self.crops else None
            self.changed()

    def geometry_changed(self, crop_id: str, values, committed: bool) -> None:
        crop = next(c for c in self.crops if c.id == crop_id)
        crop.x, crop.y, crop.width, crop.height = values
        self.dirty = True
        self.editor.viewport().update()
        self.populate_fields()
        if committed:
            self.persist()

    def apply_fields(self, source: str = "") -> None:
        if self.updating or not self.pil_image or not (crop := self.active_crop()):
            return
        name = self.name_edit.text().strip()
        if not name:
            self.name_edit.setText(crop.name)
            return
        x, y, w, h = (self.geometry_fields[k].value() for k in ("x", "y", "width", "height"))
        # Los controles redondean su presentación: no reescribir geometría al renombrar.
        if source:
            ratio = crop.ratio_width/crop.ratio_height if crop.locked else None
            if source == "height" and ratio:
                w = h * ratio
            crop.x, crop.y, crop.width, crop.height = fit_rect(x, y, w, h, *self.pil_image.size, ratio)
        crop.name = name
        crop.output_width, crop.output_height = self.output_width.value(), self.output_height.value()
        self.changed()

    def ratio_changed(self, index: int) -> None:
        if self.updating or index <= 0:
            return
        if crop := self.active_crop():
            crop.ratio_width, crop.ratio_height = self.ratio_combo.itemData(index)
            crop.locked = True
            self.fit_active_ratio()

    def custom_ratio_changed(self) -> None:
        if not self.updating and (crop := self.active_crop()):
            crop.ratio_width, crop.ratio_height = self.ratio_width.value(), self.ratio_height.value()
            if crop.locked:
                self.fit_active_ratio()
            else:
                self.changed()

    def lock_changed(self, checked: bool) -> None:
        if crop := self.active_crop():
            crop.locked = checked
            if checked:
                self.fit_active_ratio()
            else:
                self.changed()

    def fit_active_ratio(self) -> None:
        if self.pil_image and (crop := self.active_crop()):
            ratio = crop.ratio_width/crop.ratio_height
            cx, cy = crop.x + crop.width/2, crop.y + crop.height/2
            w, h = crop.width, crop.width / ratio
            crop.x, crop.y, crop.width, crop.height = fit_rect(cx-w/2, cy-h/2, w, h, *self.pil_image.size, ratio)
            self.changed()

    def correct_ratio(self) -> None:
        if self.pil_image and (crop := self.active_crop()):
            crop.ratio_width, crop.ratio_height = crop.output_width, crop.output_height
            crop.locked = True
            self.fit_active_ratio()

    def start_export(self) -> None:
        if not self.project or not self.persist():
            return
        if self.worker:
            if self.worker.isRunning():
                return
            self.worker.deleteLater()
            self.worker = None
        options = ExportOptions(self)
        if not options.exec():
            return
        folder = QFileDialog.getExistingDirectory(self, "Carpeta de exportación")
        if not folder:
            return
        jobs = []
        records = [self.current_image] if options.scope.currentIndex() == 1 and self.current_image else self.images
        try:
            for record in records:
                for number, crop in enumerate(self.repository.crops(record.id), 1):
                    jobs.append(ExportJob(Path(self.project.folder)/record.relative_path, replace(crop), number))
        except Exception as exc:
            QMessageBox.critical(self, "No se pudo preparar la exportación", str(exc))
            return
        if not jobs:
            QMessageBox.information(self, "Sin recortes", "No hay recortes para exportar.")
            return
        self.progress = QProgressDialog("Exportando recortes…", "Cancelar", 0, len(jobs), self)
        self.progress.setWindowTitle("Exportación")
        self.progress.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress.setMinimumDuration(0)
        self.progress.setAutoClose(False)
        self.progress.setAutoReset(False)
        self.worker = ExportWorker(jobs, Path(folder), options.format.currentText(), options.quality.value(), self)
        self.progress.canceled.connect(self.worker.cancel_event.set)
        self.worker.progress.connect(lambda value, total: self.progress.setValue(value))
        self.worker.completed.connect(self.export_completed)
        self.worker.finished.connect(self.update_actions)
        self.worker.start()
        self.update_actions()

    def export_completed(self, result: ExportResult) -> None:
        self.progress.close()
        text = f"{len(result.written)} recortes exportados."
        if result.cancelled:
            text += " Exportación cancelada; se conservan los archivos completados."
        if result.errors:
            text += f"\n{len(result.errors)} errores."
        message = QMessageBox(self)
        message.setWindowTitle("Resultado de exportación")
        message.setText(text)
        if result.errors:
            message.setDetailedText("\n".join(result.errors))
        message.exec()
        self.update_actions()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel_event.set()
            self.statusBar().showMessage("Cancelando exportación. Cierra la ventana cuando finalice.")
            event.ignore()
            return
        if not self.persist():
            QMessageBox.warning(self, "Cambios pendientes", "No se puede cerrar hasta guardar los cambios. Usa Reintentar guardado.")
            event.ignore()
            return
        self.thumb_timer.stop()
        if self.pil_image:
            self.pil_image.close()
        self.repository.close()
        event.accept()
