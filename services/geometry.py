from models.entities import Crop, Template, identifier


def centered_rect(image_width: float, image_height: float, ratio: float) -> tuple[float, float, float, float]:
    if image_width <= 0 or image_height <= 0 or ratio <= 0:
        raise ValueError("Dimensiones inválidas.")
    width = min(image_width, image_height * ratio)
    height = width / ratio
    return (image_width - width) / 2, (image_height - height) / 2, width, height


def from_template(template: Template, image_id: str, width: int, height: int, number: int) -> Crop:
    x, y, w, h = centered_rect(width, height, template.width / template.height)
    a, b = template.ratio
    return Crop(identifier(), image_id, f"{template.name} {number}", x, y, w, h,
                template.width, template.height, a, b, True, template.id)


def fit_rect(x: float, y: float, width: float, height: float, iw: float, ih: float,
             ratio: float | None = None) -> tuple[float, float, float, float]:
    """Normaliza una edición numérica conservando la proporción solicitada."""
    width, height = max(0.01, width), max(0.01, height)
    if ratio is not None:
        height = width / ratio
    scale = min(1.0, iw / width, ih / height)
    width, height = width * scale, height * scale
    return max(0, min(x, iw - width)), max(0, min(y, ih - height)), width, height


def resize_rect(box: tuple[float, float, float, float], handle: str,
                px: float, py: float, iw: float, ih: float,
                ratio: float | None) -> tuple[float, float, float, float]:
    """Redimensiona desde el lado opuesto; los bordes usan el centro opuesto."""
    x, y, w, h = box
    left, right, top, bottom = "w" in handle, "e" in handle, "n" in handle, "s" in handle
    px, py = max(0, min(px, iw)), max(0, min(py, ih))
    minimum = min(0.01, iw, ih)
    if ratio is None:
        x2, y2 = x + w, y + h
        if left: x = min(px, x2 - minimum)
        if right: x2 = max(px, x + minimum)
        if top: y = min(py, y2 - minimum)
        if bottom: y2 = max(py, y + minimum)
        return x, y, x2 - x, y2 - y
    ax = x + w if left else x if right else x + w / 2
    ay = y + h if top else y if bottom else y + h / 2
    if left or right:
        new_w = max(minimum, ax - px if left else px - ax)
        if top or bottom:
            new_w = max(new_w, max(minimum, ay - py if top else py - ay) * ratio)
    else:
        new_w = max(minimum, ay - py if top else py - ay) * ratio
    max_w = ax if left else iw - ax if right else 2 * min(ax, iw - ax)
    max_h = ay if top else ih - ay if bottom else 2 * min(ay, ih - ay)
    new_w = min(new_w, max_w, max_h * ratio)
    new_h = new_w / ratio
    nx = ax - new_w if left else ax if right else ax - new_w / 2
    ny = ay - new_h if top else ay if bottom else ay - new_h / 2
    return nx, ny, new_w, new_h
