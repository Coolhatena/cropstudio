import sys
import json
import os
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from storage.repository import Repository
from ui.window import MainWindow


def main() -> int:
    smoke_result = None
    if "--smoke-test" in sys.argv:
        index = sys.argv.index("--smoke-test")
        smoke_result = Path(sys.argv[index + 1]).resolve()
        del sys.argv[index:index + 2]
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv)
    app.setApplicationName("Crop Studio")
    app.setOrganizationName("CropStudio")
    try:
        repository = Repository(smoke_result.with_suffix(".sqlite3")) if smoke_result else None
        window = MainWindow(repository)
    except Exception as exc:
        if smoke_result:
            smoke_result.write_text(json.dumps({"ok": False, "error": str(exc)}), encoding="utf-8")
            return 1
        QMessageBox.critical(None, "Crop Studio no pudo iniciar", str(exc))
        return 1
    window.show()
    if smoke_result:
        def finish_smoke() -> None:
            smoke_result.write_text(json.dumps({"ok": True, "templates": len(window.templates),
                                                "title": window.windowTitle()}), encoding="utf-8")
            window.close()
        QTimer.singleShot(300, finish_smoke)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
