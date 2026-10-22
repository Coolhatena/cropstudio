from collections.abc import Callable

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                              QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox,
                              QPushButton, QSpinBox, QVBoxLayout)

from models.entities import Template
from storage.repository import Repository


class TemplateForm(QDialog):
    def __init__(self, template: Template | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editar plantilla" if template else "Nueva plantilla")
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
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        self.update_ratio()

    def update_ratio(self) -> None:
        a, b = Template("", "proporción", self.width.value(), self.height.value()).ratio
        self.ratio.setText(f"{a}:{b}")

    def validate(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, "Nombre requerido", "Escribe un nombre para la plantilla.")
            return
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
        dialog = TemplateForm(parent=self)
        if dialog.exec():
            result = self.repository.create_template(dialog.name.text(), dialog.width.value(), dialog.height.value())
            self.refresh(result.id)

    def edit(self) -> None:
        if template := self.selected():
            dialog = TemplateForm(template, self)
            if dialog.exec():
                self.repository.update_template(Template(template.id, dialog.name.text().strip(), dialog.width.value(), dialog.height.value()))
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
    def __init__(self, parent=None):
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
