#!/usr/bin/env python3
"""Создать проекты Яндекс Заданий и управлять полным циклом разметки."""

import argparse
import json
import os
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from app.api import API, ROOT, APIError, PipelineBusy, pipeline_lock
from app.deployment import setup
from app.export import export_golden
from app.replay import replay
from app.review import accept_photo
from app.worker import cycle, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("plan", help="локально собрать пулы и очередь проверки по входным данным")
    archive = commands.add_parser("replay", help="пересчитать разметку по сохранённым голосам без API")
    archive.add_argument("--output", type=Path, default=ROOT / "golden.jsonl")
    start = commands.add_parser("start", help="загрузить задания, открыть пулы и запустить обработчик")
    start.add_argument("--interval", type=int, default=60, help="интервал опроса API в секундах")
    commands.add_parser("status", help="показать итог последнего цикла")
    commands.add_parser("export", help="выгрузить полный набор в state/golden.jsonl")
    accept = commands.add_parser("accept", help="принять текущие рамки после двух отклонённых версий")
    accept.add_argument("acceptance_id", help="идентификатор версии из state/acceptance_queue.json")
    args = parser.parse_args()
    os.umask(0o077)
    state = ROOT / "state"
    if args.action == "replay":
        if args.output.resolve() == (ROOT / "reference/golden.jsonl").resolve():
            parser.error("Выберите путь для нового результата вне контрольного файла.")
        print(replay(args.output), args.output)
        return
    if args.action == "plan":
        with TemporaryDirectory() as temp:
            api = API(False, state_dir=temp)
            with closing(api.db):
                setup(api)
                print(json.dumps(cycle(api), ensure_ascii=False))
                print(dict(api.db.execute("SELECT kind,count(*) FROM objects GROUP BY kind")))
        return
    if args.action == "status":
        status = state / "status.json"
        print(status.read_text() if status.exists() else "Обработчик ещё не завершил цикл.")
        return
    if args.action == "export":
        with pipeline_lock(state):
            print(export_golden(state, state / "golden.jsonl"), state / "golden.jsonl")
        return
    if args.action == "start" and args.interval < 1:
        parser.error("--interval должен быть положительным")
    api = API(True)
    with closing(api.db):
        if args.action == "start":
            with pipeline_lock(state / "worker"):
                with pipeline_lock(state):
                    setup(api)
                run(api, args.interval)
        else:
            with pipeline_lock(state):
                accept_photo(api, args.acceptance_id)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, APIError, PipelineBusy) as exc:
        raise SystemExit(str(exc))
