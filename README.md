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

В Kaggle включи GPU и Internet, склонируй репозиторий в `/kaggle/working/data-labeling-shad` и открой нужный ноутбук из списка выше. В окружении с CUDA и установленным PyTorch добавь пакеты для метрик из раздела выше и зависимости для нужного прогона. Например, для строгого Qwen:

```bash
python -m pip install accelerate "transformers==4.57.1"
```

Для бейзлайнов подставь версию из таблицы. Для Grounding DINO и OWLv2 также нужен `torchvision`, совместимый с установленным PyTorch. После переустановки импортированных пакетов перезапусти ядро. В ноутбуке включи флаг `RERUN_...` нужной модели и выполни её ячейку. Общий код находится в [workflow.py](model_comparison/workflow.py).

| Прогон | Transformers | PyTorch в сохранённых настройках |
|---|---|---|
| Grounding DINO и OWLv2 | `5.20.2` | `2.11.0+cu130` |
| Qwen, исходный бейзлайн | `5.22.1` | `2.14.1+cu130` |
| Qwen, уточнённый промпт и Контест | `4.57.1` | `2.11.0+cu130` |

У сохранённых прогонов Qwen различались окружения. Чтобы проверить эффект промпта отдельно, в ноутбуке экспериментов включи оба флага и `SAME_ENVIRONMENT=True` в одном окружении с Transformers 4.57.1. Результаты повторных прогонов сохраняются в `runs/`. Конфигурации берутся из [настроек бейзлайнов](model_comparison/results/raw/) и [настроек Qwen](model_comparison/results/experiments/qwen/qwen.experiment.json).

Исходные [Kaggle-ноутбуки](model_comparison/notebooks/kaggle/) содержат выводы, сохранённые при первоначальной работе. Для повторного запуска используй ноутбуки из списка выше.

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
