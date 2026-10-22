from dataclasses import replace
from pathlib import Path
import sqlite3

import pytest

from models.entities import Template
from services.geometry import from_template
from storage.repository import Repository


def image_record(repo, tmp_path):
    project = repo.open_project(tmp_path)
    return repo.sync_images(project, ["producto.jpg"])[0]


def test_template_crud_defaults_and_restart(tmp_path):
    db = tmp_path / "data.sqlite3"
    repo = Repository(db)
    assert len(repo.templates()) == 4
    assert repo.default_template_id() == repo.templates()[0].id
    custom = repo.create_template("Especial", 1234, 567)
    copy = repo.duplicate_template(custom)
    assert copy.id != custom.id and copy.name == "Especial copia"
    assert Template("", "x", 1200, 800).ratio == (3, 2)
    repo.set_default(custom.id)
    repo.close()
    repo = Repository(db)
    assert repo.default_template_id() == custom.id
    assert custom in repo.templates()
    repo.delete_template(custom.id)
    assert repo.default_template_id() == repo.templates()[0].id
    for template in repo.templates():
        repo.delete_template(template.id)
    assert repo.default_template_id() is None
    repo.close()
    repo = Repository(db)
    assert repo.templates() == []  # No repoblar plantillas eliminadas.
    first = repo.create_template("Primera", 10, 20)
    assert repo.default_template_id() == first.id
    repo.close()


@pytest.mark.parametrize("name,width,height", [(" ", 5, 5), ("x", 0, 2), ("x", -1, 2), ("x", 1.2, 3)])
def test_template_validation(repository, name, width, height):
    with pytest.raises(ValueError):
        repository.create_template(name, width, height)


def test_snapshot_survives_edit_delete_and_restart(tmp_path):
    db = tmp_path / "data.sqlite3"
    repo = Repository(db)
    image = image_record(repo, tmp_path)
    template = repo.templates()[1]
    crop = from_template(template, image.id, 600, 400, 1)
    repo.save_crops(image.id, [crop, crop.duplicate()])
    repo.update_template(replace(template, name="Otro", width=17, height=31))
    assert repo.crops(image.id)[0] == crop
    repo.delete_template(template.id)
    repo.close()
    repo = Repository(db)
    restored = repo.crops(image.id)
    assert len(restored) == 2
    assert restored[0] == replace(crop, template_id=None)
    repo.save_crops(image.id, [crop])  # Una referencia obsoleta tampoco rompe el guardado.
    assert repo.crops(image.id)[0].template_id is None
    repo.close()


def test_global_templates_multiple_projects_and_missing_images(repository, tmp_path):
    template = repository.create_template("Global", 90, 160)
    for name in ("a", "b"):
        project = repository.open_project(tmp_path / name)
        image = repository.sync_images(project, ["ñ/producto.webp"])[0]
        repository.save_crops(image.id, [from_template(template, image.id, 300, 300, 1)])
        assert repository.crops(image.id)[0].template_id == template.id
        assert repository.open_project(tmp_path / name).id == project.id
        assert not repository.sync_images(project, [])[0].available
        assert len(repository.crops(image.id)) == 1
        assert repository.sync_images(project, ["ñ/producto.webp"])[0].available


def test_save_is_atomic_on_failure(repository, tmp_path):
    record = image_record(repository, tmp_path)
    crop = from_template(repository.templates()[0], record.id, 100, 100, 1)
    repository.save_crops(record.id, [crop])
    with pytest.raises(sqlite3.IntegrityError):
        repository.save_crops(record.id, [replace(crop, width=0)])
    assert repository.crops(record.id) == [crop]


@pytest.fixture
def legacy_database(tmp_path):
    """Base versión 1 independiente del inicializador de producción actual."""
    path = tmp_path / "v1.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript("""
        PRAGMA foreign_keys = ON;
        CREATE TABLE projects (id TEXT PRIMARY KEY, folder TEXT NOT NULL UNIQUE);
        CREATE TABLE images (id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
            relative_path TEXT NOT NULL, available INTEGER NOT NULL DEFAULT 1, UNIQUE(project_id, relative_path));
        CREATE TABLE templates (id TEXT PRIMARY KEY, name TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL);
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT REFERENCES templates(id) ON DELETE SET NULL);
        CREATE TABLE crops (id TEXT PRIMARY KEY, image_id TEXT NOT NULL REFERENCES images(id), name TEXT NOT NULL,
            x REAL NOT NULL, y REAL NOT NULL, width REAL NOT NULL, height REAL NOT NULL,
            output_width INTEGER NOT NULL, output_height INTEGER NOT NULL,
            ratio_width REAL NOT NULL, ratio_height REAL NOT NULL, locked INTEGER NOT NULL,
            template_id TEXT REFERENCES templates(id) ON DELETE SET NULL);
        INSERT INTO projects VALUES ('project', 'C:/Fotos');
        INSERT INTO images VALUES ('image', 'project', 'sub/ñ.png', 1);
        INSERT INTO templates VALUES ('template', 'Existente', 1200, 800);
        INSERT INTO settings VALUES ('default_template', 'template');
        INSERT INTO crops VALUES ('crop', 'image', 'Guardado', 10.25, 20.5, 150, 100, 1200, 800, 3, 2, 1, 'template');
        PRAGMA user_version = 1;
        """)
    return path


def test_migration_preserves_legacy_data_and_runs_once(legacy_database):
    repo = Repository(legacy_database)
    assert repo.db.execute("PRAGMA user_version").fetchone()[0] == 2
    assert repo.db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert repo.default_template_id() == "template"
    assert repo.templates() == [Template("template", "Existente", 1200, 800)]
    assert repo.images("project")[0].relative_path == "sub/ñ.png"
    assert repo.db.execute("SELECT folder FROM projects").fetchone()[0] == "C:/Fotos"
    saved = repo.crops("image")[0]
    assert (saved.id, saved.x, saved.y, saved.width, saved.height, saved.template_id) == ("crop", 10.25, 20.5, 150, 100, "template")
    automatic = from_template(repo.templates()[0], "image", 600, 400, 1)
    assert (automatic.x, automatic.y, automatic.width, automatic.height) == (0, 0, 600, 400)
    repo.close()
    repo = Repository(legacy_database)
    assert repo.crops("image") == [saved]
    assert len(repo.templates()) == 1
    repo.close()


def test_migration_rolls_back_schema_and_version_on_failure(legacy_database):
    class FailingMigration(Repository):
        def _migrate_v2(self):
            alters = 0

            def authorizer(action, *args):
                nonlocal alters
                if action == sqlite3.SQLITE_ALTER_TABLE:
                    alters += 1
                    if alters == 3:
                        return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK

            self.db.set_authorizer(authorizer)
            super()._migrate_v2()

    with pytest.raises(sqlite3.DatabaseError):
        FailingMigration(legacy_database)
    with sqlite3.connect(legacy_database) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert [row[1] for row in db.execute("PRAGMA table_info(templates)")] == ["id", "name", "width", "height"]
        assert db.execute("SELECT id FROM crops").fetchone()[0] == "crop"
    # Un segundo intento válido funciona sin reparaciones manuales.
    repo = Repository(legacy_database)
    assert repo.templates()[0].geometry is None
    repo.close()


def test_fixed_geometry_crud_precision_and_snapshot(tmp_path):
    path = tmp_path / "fixed.sqlite3"
    repo = Repository(path)
    image = image_record(repo, tmp_path)
    default = repo.default_template_id()
    geometry = (1.123456789012345, 2.987654321098765, 120.1234567890123, 80.0823045260082)
    template = repo.create_template("Precisa", 1200, 800, crop_x=geometry[0], crop_y=geometry[1],
                                    crop_width=geometry[2], crop_height=geometry[3])
    copy = repo.duplicate_template(template)
    assert copy.geometry == template.geometry == geometry
    assert copy.id != template.id
    assert repo.default_template_id() == default
    crop = from_template(template, image.id, 300, 200, 1)
    repo.save_crops(image.id, [crop])
    repo.update_template(replace(template, crop_x=30, crop_y=40, crop_width=60, crop_height=40))
    assert repo.crops(image.id) == [crop]
    repo.close()
    repo = Repository(path)
    assert next(t for t in repo.templates() if t.id == copy.id) == copy
    edited = next(t for t in repo.templates() if t.id == template.id)
    assert edited.geometry == (30, 40, 60, 40)
    repo.delete_template(template.id)
    assert repo.crops(image.id) == [replace(crop, template_id=None)]
    repo.close()


def test_database_rejects_partial_geometry(repository):
    template = repository.templates()[0]
    with pytest.raises(sqlite3.IntegrityError), repository.db:
        repository.db.execute("UPDATE templates SET crop_x=5 WHERE id=?", (template.id,))
    assert repository.templates()[0].geometry is None
