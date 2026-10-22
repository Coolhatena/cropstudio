import os
import sqlite3
from dataclasses import astuple
from pathlib import Path

from models.entities import Crop, ImageRecord, Project, Template, identifier


def database_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "CropStudio"
    root.mkdir(parents=True, exist_ok=True)
    return root / "cropstudio.sqlite3"


class Repository:
    def __init__(self, path: Path | str | None = None):
        self.db = sqlite3.connect(path if path is not None else database_path())
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA busy_timeout = 3000")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > 1:
            raise ValueError("La base de datos pertenece a una versión más reciente.")
        if version == 0:
            self._initialize()

    def _initialize(self) -> None:
        self.db.executescript("""
        BEGIN;
        CREATE TABLE projects (id TEXT PRIMARY KEY, folder TEXT NOT NULL UNIQUE);
        CREATE TABLE images (id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
            relative_path TEXT NOT NULL, available INTEGER NOT NULL DEFAULT 1,
            UNIQUE(project_id, relative_path));
        CREATE TABLE templates (id TEXT PRIMARY KEY, name TEXT NOT NULL CHECK(length(trim(name)) > 0),
            width INTEGER NOT NULL CHECK(width > 0), height INTEGER NOT NULL CHECK(height > 0));
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT REFERENCES templates(id) ON DELETE SET NULL);
        CREATE TABLE crops (id TEXT PRIMARY KEY, image_id TEXT NOT NULL REFERENCES images(id),
            name TEXT NOT NULL, x REAL NOT NULL, y REAL NOT NULL, width REAL NOT NULL CHECK(width > 0),
            height REAL NOT NULL CHECK(height > 0), output_width INTEGER NOT NULL CHECK(output_width > 0),
            output_height INTEGER NOT NULL CHECK(output_height > 0), ratio_width REAL NOT NULL,
            ratio_height REAL NOT NULL, locked INTEGER NOT NULL,
            template_id TEXT REFERENCES templates(id) ON DELETE SET NULL);
        CREATE INDEX crops_image ON crops(image_id);
        CREATE INDEX images_project ON images(project_id);
        """)
        with self.db:
            first_id = None
            for name, w, h in [("Producto cuadrado", 1000, 1000), ("Producto horizontal", 1200, 800),
                               ("Banner", 1920, 1080), ("Historia vertical", 1080, 1920)]:
                template_id = identifier()
                first_id = first_id or template_id
                self.db.execute("INSERT INTO templates VALUES (?, ?, ?, ?)", (template_id, name, w, h))
            self.db.execute("INSERT INTO settings VALUES ('default_template', ?)", (first_id,))
            self.db.execute("PRAGMA user_version = 1")

    def close(self) -> None:
        self.db.close()

    def templates(self) -> list[Template]:
        return [Template(**dict(row)) for row in self.db.execute("SELECT * FROM templates ORDER BY rowid")]

    def default_template_id(self) -> str | None:
        row = self.db.execute("SELECT value FROM settings WHERE key='default_template'").fetchone()
        return row[0] if row else None

    def set_default(self, template_id: str | None) -> None:
        with self.db:
            self.db.execute("INSERT INTO settings VALUES ('default_template', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (template_id,))

    def create_template(self, name: str, width: int, height: int) -> Template:
        template = Template(identifier(), name.strip(), width, height)
        with self.db:
            self.db.execute("INSERT INTO templates VALUES (?, ?, ?, ?)", astuple(template))
            if self.default_template_id() is None:
                self.db.execute("INSERT INTO settings VALUES ('default_template', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (template.id,))
        return template

    def update_template(self, template: Template) -> None:
        with self.db:
            self.db.execute("UPDATE templates SET name=?, width=?, height=? WHERE id=?",
                            (template.name.strip(), template.width, template.height, template.id))

    def duplicate_template(self, template: Template) -> Template:
        return self.create_template(template.name + " copia", template.width, template.height)

    def delete_template(self, template_id: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM templates WHERE id=?", (template_id,))
            if self.default_template_id() is None:
                row = self.db.execute("SELECT id FROM templates ORDER BY rowid LIMIT 1").fetchone()
                self.db.execute("UPDATE settings SET value=? WHERE key='default_template'", (row[0] if row else None,))

    def open_project(self, folder: Path) -> Project:
        folder_string = str(folder.resolve())
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO projects VALUES (?, ?)", (identifier(), folder_string))
        row = self.db.execute("SELECT * FROM projects WHERE folder=?", (folder_string,)).fetchone()
        return Project(**dict(row))

    def sync_images(self, project: Project, paths: list[str]) -> list[ImageRecord]:
        with self.db:
            self.db.execute("UPDATE images SET available=0 WHERE project_id=?", (project.id,))
            for relative in paths:
                self.db.execute("""INSERT INTO images VALUES (?, ?, ?, 1)
                    ON CONFLICT(project_id, relative_path) DO UPDATE SET available=1""", (identifier(), project.id, relative))
        return self.images(project.id)

    def images(self, project_id: str) -> list[ImageRecord]:
        return [ImageRecord(**dict(row)) for row in self.db.execute("SELECT * FROM images WHERE project_id=? ORDER BY relative_path COLLATE NOCASE", (project_id,))]

    def crops(self, image_id: str) -> list[Crop]:
        return [Crop(**dict(row)) for row in self.db.execute("SELECT * FROM crops WHERE image_id=? ORDER BY rowid", (image_id,))]

    def crop_counts(self, project_id: str) -> dict[str, int]:
        return dict(self.db.execute("""SELECT images.id, COUNT(crops.id) FROM images LEFT JOIN crops ON crops.image_id=images.id
            WHERE images.project_id=? GROUP BY images.id""", (project_id,)))

    def save_crops(self, image_id: str, crops: list[Crop]) -> None:
        """Sustituye una lista de forma atómica; conserva referencias solo si existen."""
        if any(c.image_id != image_id for c in crops):
            raise ValueError("Los recortes no corresponden a la imagen.")
        valid_templates = {t.id for t in self.templates()}
        with self.db:
            self.db.execute("DELETE FROM crops WHERE image_id=?", (image_id,))
            for crop in crops:
                values = list(astuple(crop))
                if crop.template_id not in valid_templates:
                    values[-1] = None
                self.db.execute("INSERT INTO crops VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", values)
