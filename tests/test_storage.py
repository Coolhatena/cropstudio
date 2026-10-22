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
