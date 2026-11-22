# Детекция бабочек

Сравниваем Grounding DINO Tiny, OWLv2 Base и Qwen3‑VL‑2B‑Instruct на 400 фотографиях. Основная метрика — объектный F1 при IoU ≥ 0.50. На командной валидации лучший результат у Qwen с уточнённым промптом, **0.8742**. Для проекта разметки см. [отчёт о bbox и review](bbox_review_pipeline/REPORT.md).

## Пересчёт результатов на CPU

Из корня репозитория в окружении Python 3.12:

```bash
python -m pip install numpy scipy pillow pandas jupyterlab
python -m jupyterlab
```

1. [Сравнение бейзлайнов](model_comparison/notebooks/baseline/models_comparison.ipynb) читает сохранённые предсказания, сверяет их с сырыми выходами и показывает метрики каждой модели на всём наборе и по группам.
2. [Эксперименты](model_comparison/notebooks/experiments/experiments.ipynb) повторяют удаление дублей у Grounding DINO, сравнивают два промпта Qwen и собирают итоговый лидерборд. Сгенерированные таблицы пишутся в `runs/tables/`.
3. [Контест](model_comparison/notebooks/production/production_labeling.py.ipynb) проверяет формат и контрольную сумму исходной посылки, затем восстанавливает точную копию.

[Бейзлайны и время](model_comparison/results/tables/leaderboard_baseline.csv) · [Сравнение экспериментов](model_comparison/results/tables/experiments_comparison.csv) · [Лидерборд](model_comparison/results/tables/leaderboard.csv) · [Метрики по группам](model_comparison/results/tables/leaderboard_by_group.csv)

## Повторный инференс на GPU

В Kaggle включи GPU (в исходном прогоне использовалась Tesla T4) и Internet. Склонируй репозиторий с обновлёнными файлами в `/kaggle/working/data-labeling-shad`. Из корня репозитория подготовь окружение:

```bash
python -m pip install --index-url https://download.pytorch.org/whl/cu130 "torch==2.11.0+cu130" "torchvision==0.26.0+cu130"
python -m pip install -r requirements.txt
```

После установки перезапусти ядро. Подходящие для продакшена версии проверяются перед инференсом: PyTorch `2.11.0+cu130` и Transformers `4.57.1`.

**Для полного сравнения открой [experiments.ipynb](model_comparison/notebooks/experiments/experiments.ipynb), поставь `RERUN_ALL=True` и выполни Run All.** Ноутбук отдельными ячейками посчитает Grounding DINO, его вариант без дублей, Qwen с обоими промптами и бейзлайн OWLv2. В паре Qwen веса, обработка и окружение общие. Меняется текст промпта. В паре Grounding DINO меняется только постобработка рамок. Сырые предсказания, настройки и таблицы появятся в `runs/production_validation/`. Повтор с тем же окружением продолжает обработку при прерывании.

В режиме по умолчанию ноутбуки пересчитывают сохранённые результаты. В `results/` лежат исторические прогоны с их фактическими версиями библиотек, в том числе два варианта Qwen, запущенные в разных окружениях. Выводы с численными значениями в ноутбуках относятся к этим прогонам. Для новых измерений смотри таблицы в `runs/production_validation/tables/`. Исходные [Kaggle-ноутбуки](model_comparison/notebooks/kaggle/) сохранены с выводами первоначальных запусков.

## Посылка

Получить точную копию [сданного JSONL](model_comparison/results/submission.jsonl) на CPU:

```bash
python -m model_comparison.run_production --replay --output-dir runs/submission_replay
```

Повторить инференс строгого Qwen на экзаменационных фото в CUDA-окружении с Transformers 4.57.1:

```bash
python -m model_comparison.run_production --output-dir runs/production_qwen
```

Новый запуск берёт промпт и ревизию весов из настроек победителя, валидирует 400 предсказаний и сообщает о побайтном совпадении с опубликованным файлом. При прерывании повтор команды с той же папкой результатов и в том же окружении продолжает обработку. После смены окружения используй другую папку.

## Файлы результатов

| Путь в `model_comparison/results/` | Содержимое |
|---|---|
| `raw/` | Кандидаты, тайминг, настройки и версии бейзлайнов |
| `predictions/` | JSONL трёх бейзлайнов |
| `experiments/dino/` | Рамки Grounding DINO после удаления дублей |
| `experiments/qwen/` | Предсказания двух промптов и конфигурации Qwen |
| `tables/` | Общие и групповые метрики |
| `preview/` | Сохранённая проверка Grounding DINO на одном кадре |
| `submission.jsonl` | Исходная посылка на 400 экзаменационных фото |
