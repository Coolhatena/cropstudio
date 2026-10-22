import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QFontDatabase

from storage.repository import Repository


@pytest.fixture
def repository(tmp_path):
    repo = Repository(tmp_path / "state.sqlite3")
    yield repo
    # Las ventanas cierran la conexión al salir.
    repo.close()


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, qapp):
    # El plugin offscreen de Windows no enumera las fuentes del sistema.
    if not QFontDatabase.families():
        for filename in ("segoeui.ttf", "segoeuib.ttf"):
            font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / filename
            if font.exists():
                QFontDatabase.addApplicationFont(str(font))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
