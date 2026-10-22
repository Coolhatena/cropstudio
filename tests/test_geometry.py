from math import isclose

import pytest

from models.entities import Template
from services.geometry import centered_rect, fit_rect, from_template, resize_rect, template_from_crop


@pytest.mark.parametrize("iw,ih", [(800, 600), (1, 1), (10, 800), (1200, 4)])
@pytest.mark.parametrize("ow,oh", [(1000, 1000), (1200, 800), (1920, 1080), (1080, 1920)])
def test_template_center_fit(iw, ih, ow, oh):
    template = Template("t", "Plantilla", ow, oh)
    crop = from_template(template, "i", iw, ih, 1)
    crop.validate(iw, ih)
    assert crop.x + crop.width / 2 == pytest.approx(iw / 2)
    assert crop.y + crop.height / 2 == pytest.approx(ih / 2)
    assert crop.width / crop.height == pytest.approx(ow / oh)
    assert crop.output_matches()


@pytest.mark.parametrize("handle", ["nw", "n", "ne", "e", "se", "s", "sw", "w"])
@pytest.mark.parametrize("point", [(-100, -100), (9999, 9999), (133, 77)])
def test_resize_locked_inside(handle, point):
    x, y, w, h = resize_rect((50, 50, 300, 200), handle, *point, 800, 600, 1.5)
    assert x >= -1e-6 and y >= -1e-6
    assert x+w <= 800+1e-6 and y+h <= 600+1e-6
    assert min(w, h) > 0
    assert w/h == pytest.approx(1.5)


def test_numeric_fit():
    x, y, w, h = fit_rect(-10, 300, 2000, 300, 100, 70, 1.5)
    assert x == 0 and y >= 0
    assert w <= 100 and y+h <= 70
    assert w/h == pytest.approx(1.5)


@pytest.mark.parametrize("geometry", [
    (None, 0, 20, 20), (0, None, 20, 20), (0, 0, None, 20), (0, 0, 20, None),
    (-1, 0, 20, 20), (0, -1, 20, 20), (0, 0, 0, 20), (0, 0, 20, -1),
    (float("nan"), 0, 20, 20), (0, float("inf"), 20, 20),
    (0, 0, float("inf"), 20), (0, 0, 20, float("nan")), (0, 0, 20, 30),
])
def test_invalid_template_geometry(geometry):
    with pytest.raises(ValueError):
        Template("t", "Inválida", 1000, 1000, *geometry)


@pytest.mark.parametrize("size", [(160, 120), (800, 600), (85, 65)])
def test_fixed_geometry_repeated_without_rescaling(size):
    template = Template("t", "Fija", 1000, 1000, 25.125, 5.125, 59.875, 59.875)
    first = from_template(template, "one", *size, 1)
    second = from_template(template, "two", *size, 2)
    assert first.id != second.id
    for crop in (first, second):
        assert (crop.x, crop.y, crop.width, crop.height) == template.geometry
        assert (crop.output_width, crop.output_height) == (1000, 1000)
        assert crop.template_id == template.id and crop.locked
        crop.validate(*size)


@pytest.mark.parametrize("geometry", [(0, 0, 200, 200), (91, 0, 10, 10), (0, 91, 10, 10)])
def test_fixed_geometry_outside_image(geometry):
    with pytest.raises(ValueError, match="^La plantilla es demasiado grande para la imagen actual$"):
        from_template(Template("t", "Fija", 1000, 1000, *geometry), "i", 100, 100, 1)


def test_fixed_geometry_exact_edges_and_template_from_crop():
    template = Template("t", "Borde", 1000, 1000, 25.125, 5.125, 74.875, 74.875)
    crop = from_template(template, "i", 100, 80, 1)
    assert crop.box == (25.125, 5.125, 100., 80.)
    saved = template_from_crop(crop)
    assert saved.id != template.id
    assert saved.geometry == template.geometry
    assert (saved.width, saved.height, saved.name) == (1000, 1000, crop.name)
