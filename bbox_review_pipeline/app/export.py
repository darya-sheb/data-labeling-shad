"""Write one record per source photo only when the whole selection is final."""

import json
from decimal import Decimal

from .materials import load


def export_golden(state, output):
    selection = state / "selection.json"
    results = state / "results.json"
    if not selection.exists() or not results.exists():
        raise ValueError("Ожидаются отбор фотографий и результаты проверки.")
    selected = set(json.loads(selection.read_text()))
    rows = json.loads(results.read_text(), parse_float=Decimal)
    return write_golden(selected, rows, output)


def write_golden(selected, rows, output):
    indexed = {r["source_image_id"]: r for r in rows}
    if (
        len(indexed) != len(rows)
        or set(indexed) != selected
        or any(r["status"] != "FINAL" or r["editable_boxes"] for r in rows)
    ):
        raise ValueError("Для части отобранных фотографий ещё нет окончательного решения.")
    photos = load("photos")
    ids = [p["image_id"] for p in photos]
    if len(set(ids)) != len(ids) or not selected.issubset(ids):
        raise ValueError("Состав исходного набора и результаты расходятся.")
    lines = []
    for photo in ids:
        boxes = []
        for frame in indexed[photo]["fixed_boxes"] if photo in selected else []:
            x, y, right, bottom = (Decimal(str(v)) if isinstance(v, float) else v for v in frame["bbox"])
            if not (0 <= x < right <= 1 and 0 <= y < bottom <= 1):
                raise ValueError(f"Рамка за пределами фото {photo}")
            values = (x, y, right - x, bottom - y)
            boxes.append(
                '{"left":%s,"top":%s,"width":%s,"height":%s}' % tuple(format(n, "f") for n in values)
            )
        lines.append('{"photo_id":%d,"boxes":[%s]}' % (int(photo), ",".join(boxes)))
    tmp = output.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(output)
    return len(lines)
