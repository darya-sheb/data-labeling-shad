# Детекция бабочек

Сравниваем Grounding DINO, OWLv2 и Qwen на 400 фотографиях с эталонными рамками. Основная метрика — F1@IoU 0.50. На валидации лучший результат показал Qwen с уточнённым промптом: **0.8742**.

## Установка

Из корня репозитория в Linux или WSL, с Python 3.12:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m jupyterlab
```

Для пересчёта метрик по сохранённым предсказаниям достаточно CPU. Для повторного инференса Qwen используйте Kaggle с GPU и доступом в интернет.

## Воспроизведение

1. [models_comparison.ipynb](notebooks/models_comparison.ipynb) — сравнение бейзлайнов. Фото и эталон лежат в [data/](data/), готовые предсказания — в [results/predictions/](results/predictions/).
2. [doubles_experiments.ipynb](notebooks/experiments/doubles_experiments.ipynb) — удаление дублей у Grounding DINO и OWLv2, пересчёт метрик и итоговый лидерборд. Для повторного запуска [qwen_experiment.ipynb](notebooks/experiments/qwen_experiment.ipynb) сначала соберите входной JSON в [prepare_butterfly_validation.ipynb](notebooks/experiments/prepare_butterfly_validation.ipynb).
3. [best_model_production.ipynb](notebooks/production/best_model_production.ipynb) — запуск выбранной модели на экзаменационных фото в Kaggle. Подключите датасет с `production_dataset.jsonl` и настройками эксперимента [qwen.experiment.json](results/experiments/qwen.experiment.json). В ячейке настроек загрузите сохранённую конфигурацию из этого JSON. Если в вашей версии ячейка ожидает `WINNER_SETTINGS`, вставьте её по инструкции в ноутбуке. После проверки 400 ID скачайте `submission.jsonl`.

**Результаты:** [бейзлайны](results/leaderboard_baseline.csv) · [эффект экспериментов](results/experiments_comparison.csv) · [общий лидерборд](results/leaderboard.csv) · [посылка](results/submission.jsonl).
