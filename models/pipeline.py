import csv
import gc
import hashlib
import json
import math
from dataclasses import asdict, replace
from io import BytesIO
from pathlib import Path
from time import perf_counter
from urllib.request import urlopen

from PIL import Image, ImageOps

from .detectors import load_detector, predict_one, select_boxes


def read_manifest(path):
    """Read the team JSON array (or JSONL) containing photo_id, url and group."""
    path = Path(path)
    with path.open(encoding="utf-8-sig") as file:
        if path.suffix.lower() == ".jsonl":
            records = [json.loads(line) for line in file if line.strip()]
        else:
            records = json.load(file)
    if not isinstance(records, list) or not records:
        raise ValueError(f"{path}: ожидается непустой список фотографий")

    rows = {}
    for index, record in enumerate(records, 1):
        if not isinstance(record, dict):
            raise ValueError(f"{path}: запись {index} должна быть объектом")
        photo_id = record.get("photo_id")
        url = record.get("url")
        group = record.get("group")
        if type(photo_id) is not int or photo_id <= 0 or photo_id in rows:
            raise ValueError(f"{path}: неверный или повторный photo_id {photo_id!r}")
        if not isinstance(url, str) or not url.strip().startswith(("https://", "http://")):
            raise ValueError(f"{path}: для photo_id {photo_id} нужна ссылка в url")
        if not isinstance(group, str) or not group.strip():
            raise ValueError(f"{path}: для photo_id {photo_id} нужна непустая group")
        rows[photo_id] = {"image": url.strip(), "group": group.strip()}
    return rows


def read_contest_manifest(path):
    path = Path(path)
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not {"photo_id", "image"}.issubset(reader.fieldnames or []):
            raise ValueError(f"{path}: нужны колонки photo_id и image")
        rows = {}
        for row in reader:
            photo_id = int(row["photo_id"])
            source = (row["image"] or "").strip()
            if not source or photo_id in rows:
                raise ValueError(f"{path}: пустой путь или повтор ID {photo_id}")
            if not source.startswith(("https://", "http://")):
                source = str((path.parent / source).resolve())
            rows[photo_id] = {"image": source, "group": (row.get("group") or "").strip()}
    if not rows:
        raise ValueError(f"Пустой манифест: {path}")
    return rows


def open_image(source):
    if source.startswith(("https://", "http://")):
        with urlopen(source, timeout=30) as response:
            source = BytesIO(response.read())
    with Image.open(source) as image:
        return ImageOps.exif_transpose(image).convert("RGB")


def read_jsonl(path):
    rows = {}
    with Path(path).open(encoding="utf-8-sig") as file:
        for line in file:
            if not line.strip():
                continue
            row = json.loads(line)
            record_id = row.get("photo_id")
            if type(record_id) is not int or record_id in rows:
                raise ValueError(f"{path}: неверный или повторный photo_id {record_id!r}")
            rows[record_id] = row
    return rows


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    temp.replace(path)


def read_settings(raw_path):
    path = Path(raw_path).with_suffix(".settings.json")
    return json.loads(path.read_text(encoding="utf-8"))


def run_model(config, manifest, raw_path, device):
    """Сохраняет кандидатов после каждого фото. При повторе обрабатывает сбои."""
    import torch
    import transformers
    from huggingface_hub import model_info

    raw_path = Path(raw_path)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path = raw_path.with_suffix(".settings.json")
    previous = read_settings(raw_path) if settings_path.exists() else None
    if raw_path.exists() and previous is None:
        raise ValueError(f"Для {raw_path} отсутствует файл настроек")

    if config.revision == "main":
        revision = previous["config"]["revision"] if previous else model_info(config.model_id).sha
        config = replace(config, revision=revision)

    settings = {
        "config": asdict(config),
        "device": device,
        "gpu": torch.cuda.get_device_name(device) if device.startswith("cuda") else None,
        "torch": str(torch.__version__),
        "transformers": transformers.__version__,
        "manifest_hash": hashlib.sha256(
            json.dumps(manifest, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }
    settings_text = json.dumps(settings, ensure_ascii=False, indent=2)
    if previous is not None and previous != json.loads(settings_text):
        raise ValueError("Настройки или набор фото изменились. Укажи новый путь для результатов.")
    if previous is None:
        settings_path.write_text(settings_text, encoding="utf-8")

    results = read_jsonl(raw_path) if raw_path.exists() else {}
    pending = [pid for pid in manifest if pid not in results or results[pid]["error"]]
    if not pending:
        return results

    detector = load_detector(config, device)
    try:
        for index, photo_id in enumerate(pending, 1):
            previous_attempts = results.get(photo_id, {}).get("attempt", 0)
            record = {"photo_id": photo_id, "attempt": previous_attempts + 1}
            try:
                image = open_image(manifest[photo_id]["image"])
                if device.startswith("cuda"):
                    torch.cuda.synchronize(device)
                started = perf_counter()
                candidates, text = predict_one(detector, config, image, device)
                if device.startswith("cuda"):
                    torch.cuda.synchronize(device)
                record.update(candidates=candidates, raw_response=text,
                              seconds=perf_counter() - started, error=None)
            except Exception as error:
                record.update(candidates=None, seconds=None,
                              raw_response=getattr(error, "raw_response", None),
                              error=f"{type(error).__name__}: {error}")

            if record["error"] or previous_attempts:
                log_path = raw_path.with_suffix(".errors.jsonl")
                with log_path.open("a", encoding="utf-8") as log:
                    log.write(json.dumps(record, ensure_ascii=False) + "\n")

            results[photo_id] = record
            write_jsonl(raw_path, results.values())
            # if index == 1 or index % 10 == 0 or index == len(pending):
            print(f"{config.name}: {index}/{len(pending)}", flush=True)
    finally:
        del detector
        gc.collect()
        if device.startswith("cuda"):
            torch.cuda.empty_cache()
    return results


def export_predictions(raw, manifest, threshold, path):
    if set(raw) != set(manifest):
        raise ValueError("ID результатов и манифеста должны совпадать")
    rows = {}
    for photo_id in manifest:
        record = raw[photo_id]
        boxes = None if record["error"] else select_boxes(record["candidates"], threshold)
        rows[photo_id] = {"photo_id": photo_id, "boxes": boxes, "error": record["error"]}
    write_jsonl(path, rows.values())
    return rows


def check_boxes(boxes):
    if not isinstance(boxes, list):
        raise ValueError("boxes должен быть списком")
    for box in boxes:
        x, y, w, h = (box[key] for key in ("left", "top", "width", "height"))
        if not all(type(v) in (float, int) and math.isfinite(v) for v in (x, y, w, h)):
            raise ValueError(f"Неверные координаты: {box}")
        if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1
                and x+w <= 1+1e-9 and y+h <= 1+1e-9):
            raise ValueError(f"Рамка выходит за границы или имеет нулевой размер: {box}")


def validate_submission(path, manifest):
    rows = read_jsonl(path)
    if len(manifest) != 400 or set(rows) != set(manifest):
        raise ValueError("В посылке должны быть ровно 400 выданных photo_id")
    if Path(path).stat().st_size > 5 * 1024**2:
        raise ValueError("Посылка больше 5 МиБ")
    for photo_id, row in rows.items():
        if row.get("error") is not None:
            raise ValueError(f"Не обработана фотография {photo_id}: {row['error']}")
        check_boxes(row["boxes"])
