from collections.abc import Callable

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                              QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox,
                              QPushButton, QSpinBox, QVBoxLayout, QWidget)

from models.entities import Template, identifier
from storage.repository import Repository


class TemplateForm(QDialog):
    def __init__(self, template: Template | None = None, parent=None, *,
                 on_save: Callable[[Template], Template | None] | None = None,
                 title: str | None = None):
        super().__init__(parent)
        self.setWindowTitle(title or ("Editar plantilla" if template else "Nueva plantilla"))
        self.template = template
        self.on_save = on_save
        self.saved_template: Template | None = None
        layout = QFormLayout(self)
        self.name = QLineEdit(template.name if template else "")
        self.width, self.height = QSpinBox(), QSpinBox()
        for field in (self.width, self.height):
            field.setRange(1, 100000)
            field.setSuffix(" px")
        self.width.setValue(template.width if template else 1000)
        self.height.setValue(template.height if template else 1000)
        self.ratio = QLabel()
        layout.addRow("Nombre", self.name)
        layout.addRow("Ancho de salida", self.width)
        layout.addRow("Alto de salida", self.height)
        layout.addRow("Proporción", self.ratio)
        self.width.valueChanged.connect(self.update_ratio)
        self.height.valueChanged.connect(self.update_ratio)
        self.fixed_geometry = QCheckBox("Guardar posición y tamaño")
        self.fixed_geometry.setChecked(template is None or template.geometry is not None)
        layout.addRow(self.fixed_geometry)
        note = QLabel("Posición y tamaño en píxeles de la imagen original, después de aplicar la orientación EXIF. Sin esta opción se usará el centrado automático.")
        note.setWordWrap(True)
        layout.addRow(note)
        self.geometry_widget = QWidget()
        geometry_layout = QFormLayout(self.geometry_widget)
        geometry_layout.setContentsMargins(0, 0, 0, 0)
        keys = ("crop_x", "crop_y", "crop_width", "crop_height")
        geometry = template.geometry if template else None
        initial = geometry or (0., 0., float(self.width.value()), float(self.height.value()))
        # Conservar los valores originales incluso si el control redondea su presentación.
        self._geometry_values = dict(zip(keys, initial))
        self.geometry_fields: dict[str, QDoubleSpinBox] = {}
        for key, label in zip(keys, ("X", "Y", "Ancho del recorte", "Alto del recorte")):
            field = QDoubleSpinBox()
            field.setDecimals(8)
            field.setRange(0 if key in {"crop_x", "crop_y"} else 0.00000001, 1000000000)
            field.setKeyboardTracking(False)
            field.setValue(self._geometry_values[key])
            field.valueChanged.connect(lambda value, key=key: self._set_geometry_value(key, value))
            self.geometry_fields[key] = field
            geometry_layout.addRow(label, field)
        self.geometry_widget.setEnabled(self.fixed_geometry.isChecked())
        self.fixed_geometry.toggled.connect(self.geometry_widget.setEnabled)
        layout.addRow(self.geometry_widget)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        self.update_ratio()

    def _set_geometry_value(self, key: str, value: float) -> None:
        self._geometry_values[key] = value

    def update_ratio(self) -> None:
        a, b = Template("", "proporción", self.width.value(), self.height.value()).ratio
        self.ratio.setText(f"{a}:{b}")

    def validate(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, "Nombre requerido", "Escribe un nombre para la plantilla.")
            return
        try:
            geometry = self._geometry_values if self.fixed_geometry.isChecked() else {}
            candidate = Template(self.template.id if self.template else identifier(),
                                 self.name.text().strip(), self.width.value(), self.height.value(), **geometry)
        except ValueError as exc:
            QMessageBox.warning(self, "Plantilla no válida", str(exc))
            return
        try:
            saved = self.on_save(candidate) if self.on_save else None
        except Exception as exc:
            QMessageBox.critical(self, "No se pudo guardar la plantilla", str(exc))
            return
        self.saved_template = saved or candidate
        self.accept()


class TemplateManager(QDialog):
    def __init__(self, repository: Repository, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.setWindowTitle("Plantillas globales")
        self.resize(700, 350)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Disponibles en todos los proyectos. Los cambios no alteran recortes existentes."))
        self.items = QListWidget()
        layout.addWidget(self.items)
        row = QHBoxLayout()
        for label, callback in [("Crear", self.create), ("Editar", self.edit), ("Duplicar", self.duplicate),
                                ("Eliminar", self.delete), ("Predeterminada", self.make_default)]:
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, fn=callback: self.attempt(fn))
            row.addWidget(button)
        layout.addLayout(row)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self.refresh()

    def attempt(self, callback: Callable) -> None:
        try:
            callback()
        except Exception as exc:
            QMessageBox.critical(self, "No se pudo guardar la plantilla", str(exc))

    def refresh(self, selected_id: str | None = None) -> None:
        self.templates = self.repository.templates()
        default = self.repository.default_template_id()
        self.items.clear()
        for index, template in enumerate(self.templates):
            self.items.addItem(("★ " if template.id == default else "") + template.label)
            if template.id == selected_id:
                self.items.setCurrentRow(index)
        if self.items.currentRow() < 0 and self.templates:
            self.items.setCurrentRow(0)

    def selected(self) -> Template | None:
        index = self.items.currentRow()
        return self.templates[index] if index >= 0 else None

    def create(self) -> None:
        dialog = TemplateForm(parent=self, on_save=self.repository.add_template)
        if dialog.exec():
            self.refresh(dialog.saved_template.id)

    def edit(self) -> None:
        if template := self.selected():
            dialog = TemplateForm(template, self, on_save=self.repository.update_template)
            if dialog.exec():
                self.refresh(template.id)

    def duplicate(self) -> None:
        if template := self.selected():
            self.refresh(self.repository.duplicate_template(template).id)

    def delete(self) -> None:
        if template := self.selected():
            if QMessageBox.question(self, "Eliminar plantilla", f"¿Eliminar «{template.name}»? Sus recortes se conservarán.") == QMessageBox.StandardButton.Yes:
                self.repository.delete_template(template.id)
                self.refresh()

    def make_default(self) -> None:
        if template := self.selected():
            self.repository.set_default(template.id)
            self.refresh(template.id)


class ExportOptions(QDialog):
    def __init__(self, parent=None, *, project_name: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Exportación")
        layout = QFormLayout(self)
        self.scope = QComboBox()
        self.scope.addItems(["Todos los recortes del proyecto", "Solo la imagen actual"])
        self.format = QComboBox()
        self.format.addItems(["JPG", "PNG", "WEBP", "SVG"])
        self.quality = QSpinBox()
        self.quality.setRange(1, 100)
        self.quality.setValue(95)
        self.format.currentTextChanged.connect(lambda name: self.quality.setEnabled(name in {"JPG", "WEBP"}))
        layout.addRow("Exportar", self.scope)
        layout.addRow("Formato", self.format)
        layout.addRow("Calidad", self.quality)
        folder_name = f"{project_name or 'nombre_del_proyecto'}_recortes"
        self.destination_note = QLabel(
            f"Seleccionarás una carpeta contenedora. Dentro se creará «{folder_name}», "
            "conservando las subcarpetas de las imágenes. Solo se crearán las carpetas necesarias para los recortes."
        )
        self.destination_note.setWordWrap(True)
        layout.addRow(self.destination_note)
        self.svg_note = QLabel("SVG incluye el recorte como imagen PNG incrustada; conserva la transparencia y no vectoriza la imagen.")
        self.svg_note.setWordWrap(True)
        self.svg_note.hide()
        self.format.currentTextChanged.connect(lambda name: self.svg_note.setVisible(name == "SVG"))
        layout.addRow(self.svg_note)
        layout.addRow(QLabel("Los nombres repetidos recibirán un sufijo. Los originales se conservan."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
