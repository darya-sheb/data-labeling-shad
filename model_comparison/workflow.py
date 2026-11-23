import json
import os
from pathlib import Path

import pandas as pd

from .models.configs import Config
from .models.detectors import select_boxes
from .models.metrics import evaluate, iou_matrix
from .models.pipeline import read_jsonl, read_manifest, run_model, write_jsonl

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RESULTS = ROOT / "model_comparison" / "results"
QWEN_EXPERIMENT = RESULTS / "experiments/qwen/qwen.experiment.json"
QWEN_WINNER = "qwen__strict_negative_prompt"
PUBLISHED = RESULTS / "submission.jsonl"
PUBLISHED_SHA256 = "093617e7c28c2e20def000d9b8e2c8b77953707b9f46235f33d56e9c03eaa0ce"


def load_validation():
    photos = read_manifest(DATA / "val_dataset.json")
    golden = read_jsonl(DATA / "golden.jsonl")
    if len(photos) != 400 or photos.keys() != golden.keys():
        raise ValueError("В датасете и эталоне должны совпадать все 400 photo_id")
    return photos, golden


def run_directory(path):
    path = Path(path).resolve()
    if path == RESULTS or RESULTS in path.parents:
        raise ValueError("Выбери папку вне опубликованных results")
    return path


def production_settings():
    return json.loads(QWEN_EXPERIMENT.read_text(encoding="utf-8"))["settings"][QWEN_WINNER]


def check_production_runtime(device="auto"):
    settings = production_settings()
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "120")

    try:
        import torch
        import torchvision
        import transformers
    except (ImportError, OSError, RuntimeError) as error:
        raise RuntimeError(
            "Не удалось загрузить зависимости для инференса. "
            "Установи сборки PyTorch и torchvision для своего устройства по model_comparison/README.md "
            "и перезапусти ядро ноутбука."
        ) from error

    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if device not in {"cpu", "cuda"}:
        raise ValueError("Устройство должно быть auto, cpu или cuda")
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA недоступна. Выбери cpu или запусти в окружении с NVIDIA GPU.")

    expected_torch = settings["torch"]
    expected_vision = "0.26.0+cu130"
    if device == "cpu":
        expected_torch = expected_torch.split("+")[0] + "+cpu"
        expected_vision = expected_vision.split("+")[0] + "+cpu"
    if (
        str(torch.__version__) != expected_torch
        or torchvision.__version__ != expected_vision
        or transformers.__version__ != settings["transformers"]
    ):
        raise RuntimeError(
            f"Для {device} нужны torch=={expected_torch}, torchvision=={expected_vision}, "
            f"transformers=={settings['transformers']}. "
            "Команды установки есть в model_comparison/README.md."
        )
    hardware = torch.cuda.get_device_name(0) if device == "cuda" else "CPU"
    print(f"{hardware} | torch {torch.__version__} | transformers {transformers.__version__}")
    return device


def infer_validation(config, photos, output_dir, device="auto"):
    output_dir = run_directory(output_dir)
    device = check_production_runtime(device)
    raw_path = output_dir / f"{config.name}.raw.jsonl"
    raw = run_model(config, photos, raw_path, device)
    if raw.keys() != photos.keys():
        raise RuntimeError(f"{config.name}: набор photo_id отличается от датасета")
    errors = sum(row["error"] is not None for row in raw.values())
    if errors:
        raise RuntimeError(f"{config.name}: {errors} ошибок. Повтори запуск с тем же каталогом: {raw_path.parent}")
    predictions = predictions_from_raw(raw, config.threshold)
    write_jsonl(output_dir / f"{config.name}.jsonl", predictions.values())
    return predictions, elapsed(raw)


def predictions_from_raw(raw, threshold):
    return {
        pid: {
            "photo_id": pid,
            "boxes": None if row["error"] else select_boxes(row["candidates"], threshold),
            "error": row["error"],
        }
        for pid, row in raw.items()
    }


def elapsed(raw):
    return sum(row["seconds"] for row in raw.values() if row["seconds"] is not None)


def baseline(name, photos, *, rerun=False, output_dir=None, device="auto"):
    settings = json.loads((RESULTS / f"raw/{name}.settings.json").read_text())
    if rerun:
        config = Config(**settings["config"])
        if name == "qwen":
            # Для пары Qwen за основу берём конфиг продакшена, меняя только текст.
            config = Config(**{**production_settings()["config"], "name": name,
                               "prompt": config.prompt})
        return infer_validation(config, photos, output_dir, device)

    raw = read_jsonl(RESULTS / f"raw/{name}.jsonl")
    published = read_jsonl(RESULTS / f"predictions/{name}.jsonl")
    if predictions_from_raw(raw, settings["config"]["threshold"]) != published:
        raise ValueError(f"Сырые и опубликованные предсказания различаются для {name}")
    return published, elapsed(raw)


def qwen_prompt_variant(photos, *, strict, rerun=False, output_dir=None, device="auto"):
    if rerun:
        if not strict:
            return baseline("qwen", photos, rerun=True, output_dir=output_dir, device=device)
        return infer_validation(Config(**production_settings()["config"]), photos, output_dir, device)

    name = QWEN_WINNER if strict else "qwen__reference"
    predictions = read_jsonl(QWEN_EXPERIMENT.with_name(f"{name}.jsonl"))
    seconds = None if strict else elapsed(read_jsonl(RESULTS / "raw/qwen.jsonl"))
    return predictions, seconds


def deduplicate(predictions, threshold=0.85):
    filtered = {}
    for pid, row in predictions.items():
        if row["error"]:
            filtered[pid] = row
            continue
        kept = []
        for box in row["boxes"]:
            if not kept or not (iou_matrix(kept, [box]) >= threshold).any():
                kept.append(box)
        filtered[pid] = {**row, "boxes": kept}
    return filtered


def measure(name, photos, golden, predictions, seconds=None):
    if predictions.keys() != photos.keys():
        raise ValueError(f"{name}: набор photo_id не совпадает с датасетом")
    totals, _ = evaluate(photos, golden, predictions)
    totals.update(run=name, inference_seconds=seconds)
    totals["ms_per_photo"] = 1000 * seconds / len(photos) if seconds is not None else None

    selected = {}
    for pid, photo in photos.items():
        selected.setdefault(photo["group"], []).append(pid)
    groups = []
    for group, ids in sorted(selected.items()):
        stats, _ = evaluate(ids, golden, predictions)
        if stats["n_negative_photos"] == stats["n_photos"]:
            for key in ("recall_50", "recall_75", "f1_50", "f1_75"):
                stats[key] = None
            for suffix in ("50", "75"):
                if not stats[f"fp_{suffix}"]:
                    stats[f"precision_{suffix}"] = None
        groups.append({"run": name, "group": group, **stats})
    return totals, groups


def leaderboard(*runs):
    return pd.DataFrame([totals for totals, _ in runs]).set_index("run").sort_values(
        "f1_50", ascending=False, kind="stable"
    )


def group_table(*runs):
    return pd.DataFrame([row for _, groups in runs for row in groups]).set_index(["run", "group"])


def compare_experiments(dino_before, dino_after, qwen_before, qwen_after):
    rows = []
    pairs = (
        ("Grounding DINO: удаление дублей", dino_before, dino_after),
        ("Qwen: уточнённый промпт", qwen_before, qwen_after),
    )
    for title, (before, _), (after, _) in pairs:
        row = {"experiment": title}
        for key in (
            "f1_50", "f1_75", "precision_50", "recall_50", "fp_50", "fn_50",
            "negative_photos_with_fp", "technical_errors",
        ):
            row[f"{key}_before"] = before[key]
            row[f"{key}_after"] = after[key]
            row[f"{key}_delta"] = after[key] - before[key]
        rows.append(row)
    return pd.DataFrame(rows).set_index("experiment")
