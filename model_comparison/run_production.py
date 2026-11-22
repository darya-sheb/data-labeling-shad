import argparse
import hashlib
import json
import os
from pathlib import Path

from .models.configs import Config
from .models.pipeline import export_predictions, run_model, validate_submission

from .workflow import PUBLISHED, PUBLISHED_SHA256, QWEN_EXPERIMENT, QWEN_WINNER, ROOT, run_directory

DEFAULT_SETTINGS = QWEN_EXPERIMENT
WINNER = QWEN_WINNER


def read_production_dataset(path):
    text = Path(path).read_text(encoding="utf-8-sig")
    rows = (
        json.loads(text) if text.lstrip().startswith("[")
        else [json.loads(line) for line in text.splitlines() if line.strip()]
    )
    if len(rows) != 400:
        raise ValueError(f"Ожидается 400 фото, получено {len(rows)}")

    manifest = {}
    for row in rows:
        photo_id = row.get("photo_id")
        if type(photo_id) is not int or photo_id <= 0 or photo_id in manifest:
            raise ValueError(f"Неверный или повторный photo_id: {photo_id!r}")
        url = row.get("photo_url")
        if not isinstance(url, str) or not url.strip().startswith(("https://", "http://")):
            raise ValueError(f"Нет ссылки photo_url: {photo_id}")
        manifest[photo_id] = {"image": url.strip()}
    return manifest


def replay_submission(output_dir, dataset_path=ROOT / "data/production_dataset.jsonl"):
    """Копирует сданный JSONL побайтно и проверяет его контрольную сумму."""
    validate_submission(PUBLISHED, read_production_dataset(dataset_path))
    published = PUBLISHED.read_bytes()
    if hashlib.sha256(published).hexdigest() != PUBLISHED_SHA256:
        raise ValueError("Контрольная сумма опубликованной посылки изменилась")
    output_dir = run_directory(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "submission.jsonl"
    draft = output_dir / "submission.pending.jsonl"
    draft.write_bytes(published)
    draft.replace(output)
    return output


def run_production(dataset_path, output_dir, settings_path=DEFAULT_SETTINGS):
    manifest = read_production_dataset(dataset_path)
    metadata = json.loads(Path(settings_path).read_text(encoding="utf-8"))
    settings = metadata["settings"][WINNER]
    config = Config(**settings["config"])
    if (
        config.name != WINNER or config.backend != "qwen"
        or not config.revision or config.revision == "main"
    ):
        raise ValueError("Нужна сохранённая конфигурация Qwen с фиксированной ревизией весов")

    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "120")

    import torch
    import transformers

    if not torch.cuda.is_available():
        raise RuntimeError("Для этого прогона включи GPU с CUDA")
    if transformers.__version__ != settings["transformers"]:
        raise RuntimeError(f"Установи transformers=={settings['transformers']}")
    print(f"GPU: {torch.cuda.get_device_name(0)} | torch: {torch.__version__}")
    if str(torch.__version__) != settings["torch"]:
        print(f"В сохранённом прогоне использовался torch {settings['torch']}")

    output_dir = run_directory(output_dir)
    raw_path = output_dir / f"{WINNER}.raw.jsonl"
    raw = run_model(config, manifest, raw_path, "cuda")
    errors = sum(row["error"] is not None for row in raw.values())
    if errors:
        log_path = raw_path.with_suffix(".errors.jsonl")
        raise RuntimeError(f"Ошибок: {errors}. Журнал: {log_path}. Повтори прогон после исправления.")

    draft = output_dir / "submission.pending.jsonl"
    submission = output_dir / "submission.jsonl"
    export_predictions(raw, manifest, config.threshold, draft)
    validate_submission(draft, manifest)
    draft.replace(submission)
    return submission


def main():
    parser = argparse.ArgumentParser(description="Запуск Qwen и проверка посылки для Контеста")
    parser.add_argument("--dataset", type=Path, default=ROOT / "data/production_dataset.jsonl")
    parser.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    parser.add_argument("--output-dir", type=Path, default=Path("production_run"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate-only", type=Path, metavar="SUBMISSION")
    mode.add_argument("--replay", action="store_true", help="Скопировать сданный JSONL без инференса")
    args = parser.parse_args()

    if args.validate_only is not None:
        validate_submission(args.validate_only, read_production_dataset(args.dataset))
        print(f"Посылка прошла проверку: {args.validate_only}")
        return

    if args.replay:
        submission = replay_submission(args.output_dir, args.dataset)
    else:
        submission = run_production(args.dataset, args.output_dir, args.settings)
        same = submission.read_bytes() == PUBLISHED.read_bytes()
        print("Совпадение с опубликованной посылкой:", "побайтное" if same else "нет")
    print(f"Посылка готова: {submission} ({submission.stat().st_size:,} байт)")


if __name__ == "__main__":
    main()
