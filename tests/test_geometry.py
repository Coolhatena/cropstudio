from math import isclose

import pytest

from models.entities import Template
from services.geometry import centered_rect, fit_rect, from_template, resize_rect


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
