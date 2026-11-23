# Детекция бабочек: сравнение моделей

Сравниваем Grounding DINO Tiny, OWLv2 Base и Qwen3-VL-2B-Instruct на 400 фотографиях командной выборки. Лучший опубликованный результат у Qwen с уточнённым промптом: объектный F1@IoU 0,50 — **0,8742**, F1@IoU 0,75 — **0,7889**. [Отчёт по моделям](results/RESULTS.md) · [Отчёт о разметке](../bbox_review_pipeline/REPORT.md)

## Подготовка окружения в VS Code

1. Откройте в VS Code **корень репозитория** `data-labeling-shad`. На Windows откройте папку в WSL. Установите расширения **Python** и **Jupyter** в той среде, где открыт проект.
2. В терминале VS Code из корня репозитория создайте и активируйте окружение на Python 3.12:

   ```bash
   python3.12 -m venv .venv
   source .venv/bin/activate
   ```

   Если `.venv` уже создано, достаточно его активировать.

3. Откройте [ноутбук экспериментов](notebooks/experiments/experiments.ipynb). В правом верхнем углу нажмите **Select Kernel → Python Environments** и выберите `.venv/bin/python` из этого репозитория. После установки зависимостей перезапустите ядро, если ноутбук уже запускался.

Все команды ниже выполняются из корня репозитория в активированном `.venv`.

## Новый инференс из фотографий

Нужен интернет для загрузки фотографий и весов. Выберите команды для своего устройства.

**CPU (в том числе WSL без NVIDIA):**

```bash
python -m pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.11.0+cpu" "torchvision==0.26.0+cpu"
python -m pip install -r requirements.txt
```

**NVIDIA GPU с поддержкой CUDA 13.0:**

```bash
python -m pip install --index-url https://download.pytorch.org/whl/cu130 "torch==2.11.0+cu130" "torchvision==0.26.0+cu130"
python -m pip install -r requirements.txt
```

В [ноутбуке экспериментов](notebooks/experiments/experiments.ipynb) поставьте **`RERUN_ALL = True`** и нажмите **Run All**. Ноутбук выберет CUDA при её доступности, иначе CPU. Он прогонит все три модели на 400 фото, проверит удаление дублей у Grounding DINO и сравнит два промпта Qwen в одном окружении.

Новые предсказания, настройки, тайминги и отчёт `RESULTS.md` появятся в `runs/production_validation/cpu/` или `runs/production_validation/cuda/`. Чтобы продолжить прерванный прогон, повторите запуск в том же окружении с той же папкой вывода. На CPU полный прогон может занять значительно больше времени. Qwen использует BF16 на CPU и FP16 на CUDA, поэтому новые метрики могут отличаться от опубликованных.

## Пересчёт опубликованных метрик на CPU

Для пересчёта из сохранённых предсказаний достаточно следующих зависимостей:

```bash
python -m pip install numpy scipy pillow pandas ipykernel
```

В [ноутбуке экспериментов](notebooks/experiments/experiments.ipynb) оставьте **`RERUN_ALL = False`** и нажмите **Run All**. Все четыре таблицы появятся в `runs/tables/`, отчёт — в `runs/RESULTS.md`. [Ноутбук бейзлайнов](notebooks/baseline/models_comparison.ipynb) можно запустить отдельно, чтобы пересчитать только сравнение трёх исходных моделей. Два опубликованных прогона Qwen выполнены с разными версиями библиотек.

## Посылка

Чтобы заново получить JSONL для Контеста, установите зависимости для инференса и запустите строгий Qwen на отдельном наборе из 400 экзаменационных фото:

```bash
python -m model_comparison.run_production --device auto --output-dir runs/production_qwen
```

Результат — `runs/production_qwen/submission.jsonl`. Скрипт проверяет формат и идентификаторы, затем сравнивает файл с опубликованным. Для явного выбора устройства укажите `--device cpu` или `--device cuda`. При смене устройства или окружения задайте другую папку вывода.

Чтобы проверить и скопировать опубликованную посылку, достаточно зависимостей для пересчёта метрик:

```bash
python -m model_comparison.run_production --replay --output-dir runs/submission_replay
```

## Опубликованные результаты

- [Отчёт](results/RESULTS.md), [итоговый лидерборд](results/tables/leaderboard.csv), [метрики по группам](results/tables/leaderboard_by_group.csv) и [сравнение экспериментов](results/tables/experiments_comparison.csv)
- [Предсказания бейзлайнов](results/predictions/), [сырые выходы, настройки и тайминги](results/raw/) и [результаты экспериментов](results/experiments/)
- [JSONL для Контеста](results/submission.jsonl)
