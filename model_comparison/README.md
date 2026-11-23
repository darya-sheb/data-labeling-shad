# Детекция бабочек

Сравниваем Grounding DINO Tiny, OWLv2 Base и Qwen3‑VL‑2B‑Instruct на 400 фотографиях. Основная метрика — объектный F1 при IoU ≥ 0.50. На командной валидации лучший результат у Qwen с уточнённым промптом, **0.8742**. [Отчёт о разметке](../bbox_review_pipeline/REPORT.md) · [Пулы и скриншоты заданий](../bbox_review_pipeline/README.md#пулы-и-интерфейсы-заданий)

В рабочем пуле проверки рамок 90,5% ответов на скрытых контрольных заданиях совпали с эталоном (152 из 168). Экзамены прошли 6 из 7 разметчиков и 9 из 10 валидаторов. [Результаты обучения, экзаменов и ханипотов](../bbox_review_pipeline/README.md#результаты-контроля-качества)

## Пересчёт результатов на CPU

Этот путь подходит для проверки опубликованных результатов на любом устройстве. PyTorch, CUDA и скачивание весов для него не нужны. Оставьте `RERUN_ALL=False`, чтобы пересчитать опубликованный отчёт.

Из корня репозитория в окружении Python 3.12:

```bash
python -m pip install numpy scipy pillow pandas jupyterlab
python -m jupyterlab
```

1. [Сравнение бейзлайнов](notebooks/baseline/models_comparison.ipynb) читает сохранённые предсказания, сверяет их с сырыми выходами и показывает метрики каждой модели на всём наборе и по группам.
2. [Эксперименты](notebooks/experiments/experiments.ipynb) повторяют удаление дублей у Grounding DINO, сравнивают два промпта Qwen и собирают итоговый лидерборд. Сгенерированные таблицы пишутся в `runs/tables/`, отчёт — в `runs/RESULTS.md`. Ноутбук экспериментов можно запустить отдельно: он формирует все четыре таблицы.
3. [Контест](#посылка) — команды для проверки и восстановления исходного JSONL. Код запуска находится в [run_production.py](run_production.py).

[Бейзлайны и время](results/tables/leaderboard_baseline.csv) · [Сравнение экспериментов](results/tables/experiments_comparison.csv) · [Лидерборд](results/tables/leaderboard.csv) · [Метрики по группам](results/tables/leaderboard_by_group.csv)

## Новый инференс из фотографий

Нужны Python 3.12, доступ к фотографиям и загрузке весов с Hugging Face. Команды выполняются из корня репозитория.

**На CPU (например, WSL без NVIDIA):**

```bash
python -m pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.11.0+cpu" "torchvision==0.26.0+cpu"
python -m pip install -r requirements.txt
```

**На NVIDIA GPU (например, Kaggle с GPU и Internet):**

```bash
python -m pip install --index-url https://download.pytorch.org/whl/cu130 "torch==2.11.0+cu130" "torchvision==0.26.0+cu130"
python -m pip install -r requirements.txt
```

В Kaggle репозиторий можно склонировать в `/kaggle/working/data-labeling-shad`. После установки выберите ядро этого окружения и перезапустите его.

Откройте [experiments.ipynb](notebooks/experiments/experiments.ipynb), задайте `RERUN_ALL=True` и выполните **Run All**. Ноутбук выберет CUDA при её доступности и CPU в остальных случаях. Он запускает Grounding DINO, OWLv2 и два варианта Qwen на всех 400 фото, повторяет удаление дублей DINO и пересчитывает отчёт. Ревизии весов берутся из сохранённых настроек. Новый прогон пишет предсказания, настройки, тайминги и отчёт в `runs/production_validation/cpu/` или `runs/production_validation/cuda/`. После остановки повторный запуск в том же окружении продолжит обработку с сохранённых строк.

На CPU новые прогоны могут занять существенно больше времени. Для весов нужен свободный диск, а для запуска Qwen — достаточный объём оперативной памяти. Qwen запускается в BF16 на CPU и FP16 на CUDA. Для сравнения новых метрик используйте отчёт текущего прогона.

В режиме по умолчанию ноутбуки пересчитывают сохранённые результаты. В `results/` лежат исторические прогоны с их фактическими версиями библиотек, в том числе два варианта Qwen, запущенные в разных окружениях. Выводы с численными значениями в ноутбуках относятся к этим прогонам. Для новых измерений смотрите таблицы в `runs/production_validation/<устройство>/tables/`. Исходные [Kaggle-ноутбуки](notebooks/kaggle/) сохранены с выводами первоначальных запусков.

## Посылка

Получить точную копию [сданного JSONL](results/submission.jsonl) на CPU:

```bash
python -m model_comparison.run_production --replay --output-dir runs/submission_replay
```

Заново получить посылку строгого Qwen из экзаменационных фотографий после установки зависимостей для выбранного устройства:

```bash
python -m model_comparison.run_production --device auto --output-dir runs/production_qwen
```

Новый запуск берёт промпт и ревизию весов из настроек победителя, валидирует 400 предсказаний и сообщает о побайтном совпадении с опубликованным файлом. При прерывании повтор команды с той же папкой результатов и в том же окружении продолжает обработку. При смене устройства или окружения укажите отдельную папку. Для явного выбора используйте `--device cpu` или `--device cuda`.

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
