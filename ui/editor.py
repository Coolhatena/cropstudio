from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from models.entities import Crop
from services.geometry import resize_rect


class CropEditor(QGraphicsView):
    selected = Signal(str)
    geometry_changed = Signal(str, object, bool)
    drawn = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor("#15181d"))
        self.setMouseTracking(True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.crops: list[Crop] = []
        self.active_id: str | None = None
        self.image_width = self.image_height = 0
        self.drawing = False
        self._mode = ""
        self._start = QPointF()
        self._original = (0., 0., 0., 0.)
        self._temporary: QRectF | None = None
        self._pan = None
        self._auto_fit = True
        self._fitting = False

    def set_image(self, image: QImage | None) -> None:
        self.scene().clear()
        self.crops = []
        self.active_id = None
        self._mode = ""
        self._temporary = None
        self.image_width = image.width() if image else 0
        self.image_height = image.height() if image else 0
        if image:
            self.scene().addPixmap(QPixmap.fromImage(image))
        self.setSceneRect(0, 0, self.image_width, self.image_height)
        self.fit_image()

    def fit_image(self) -> None:
        self._auto_fit = True
        if self.image_width and not self._fitting:
            self._fitting = True
            try:
                self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            finally:
                self._fitting = False

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._auto_fit:
            self.fit_image()

    def set_crops(self, crops: list[Crop], active_id: str | None) -> None:
        self.crops, self.active_id = crops, active_id
        self.viewport().update()

    def active(self) -> Crop | None:
        return next((c for c in self.crops if c.id == self.active_id), None)

    def handles(self, crop: Crop) -> dict[str, QPointF]:
        x, y, w, h = crop.x, crop.y, crop.width, crop.height
        return {"nw": QPointF(x, y), "n": QPointF(x+w/2, y), "ne": QPointF(x+w, y),
                "e": QPointF(x+w, y+h/2), "se": QPointF(x+w, y+h), "s": QPointF(x+w/2, y+h),
                "sw": QPointF(x, y+h), "w": QPointF(x, y+h/2)}

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        active = self.active()
        if active:
            path = QPainterPath()
            path.addRect(self.sceneRect())
            path.addRect(QRectF(active.x, active.y, active.width, active.height))
            painter.fillPath(path, QColor(0, 0, 0, 130))
        for crop in self.crops:
            pen = QPen(QColor("#52dcc2" if crop is active else "#d9e3f0"), 2)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(crop.x, crop.y, crop.width, crop.height))
            if crop is active:
                size = 7 / max(self.transform().m11(), 0.0001)
                painter.setBrush(QColor("#52dcc2"))
                for point in self.handles(crop).values():
                    painter.drawRect(QRectF(point.x()-size/2, point.y()-size/2, size, size))
        if self._temporary:
            pen = QPen(QColor("#f6cc76"), 2, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self._temporary)

    def bounded(self, point: QPointF) -> QPointF:
        return QPointF(max(0, min(point.x(), self.image_width)), max(0, min(point.y(), self.image_height)))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton or (event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._pan = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton or not self.image_width:
            super().mousePressEvent(event)
            return
        point = self.bounded(self.mapToScene(event.position().toPoint()))
        self._start = point
        if self.drawing:
            self._mode = "draw"
            self._temporary = QRectF(point, point)
        else:
            active = self.active()
            tolerance = 10 / max(self.transform().m11(), 0.0001)
            if active:
                for handle, location in self.handles(active).items():
                    if (location-point).manhattanLength() <= tolerance:
                        self._mode = handle
                        self._original = (active.x, active.y, active.width, active.height)
                        event.accept()
                        return
            # Al hacer clic de nuevo sobre una superposición, recorrer los recortes.
            hits = [c for c in reversed(self.crops) if QRectF(c.x, c.y, c.width, c.height).contains(point)]
            if hits:
                target = hits[0]
                if active in hits and len(hits) > 1:
                    target = hits[(hits.index(active)+1) % len(hits)]
                self.active_id = target.id
                self.selected.emit(target.id)
                self._original = (target.x, target.y, target.width, target.height)
                self._mode = "move"
        self.viewport().update()
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._pan is not None:
            delta = event.position().toPoint() - self._pan
            self._pan = event.position().toPoint()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value()-delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value()-delta.y())
            return
        point = self.bounded(self.mapToScene(event.position().toPoint()))
        if self._mode == "draw":
            self._temporary = QRectF(self._start, point).normalized()
            self.viewport().update()
        elif self._mode and (crop := self.active()):
            x, y, w, h = self._original
            if self._mode == "move":
                values = (max(0, min(x+point.x()-self._start.x(), self.image_width-w)),
                          max(0, min(y+point.y()-self._start.y(), self.image_height-h)), w, h)
            else:
                values = resize_rect(self._original, self._mode, point.x(), point.y(),
                                     self.image_width, self.image_height,
                                     crop.ratio_width/crop.ratio_height if crop.locked else None)
            self.geometry_changed.emit(crop.id, values, False)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._pan is not None:
            self._pan = None
            self.unsetCursor()
            return
        if self._mode == "draw" and self._temporary:
            rect = self._temporary
            self._temporary = None
            self.drawing = False
            self.unsetCursor()
            if rect.width() >= 1 and rect.height() >= 1:
                self.drawn.emit((rect.x(), rect.y(), rect.width(), rect.height()))
        elif self._mode and (crop := self.active()):
            self.geometry_changed.emit(crop.id, (crop.x, crop.y, crop.width, crop.height), True)
        self._mode = ""
        self.viewport().update()
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        scale = self.transform().m11() * factor
        if 0.005 <= scale <= 100:
            self._auto_fit = False
            self.scale(factor, factor)
        event.accept()
