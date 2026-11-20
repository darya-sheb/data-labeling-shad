"""Poll submissions, release eligible work and materialize the finished dataset."""

import json
import logging
import signal
import threading
from collections import Counter
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from time import monotonic

from .activation import open_ready_pools
from .api import pipeline_lock, save_json
from .export import export_golden
from .materials import CONFIG
from .review import process
from .routing import route
from .work_quality import release_expired_work_skills
from .worker_log import event


def fetch(api):
    changed = 0
    for pool in CONFIG["rewards_rub"]:
        statuses = "SUBMITTED,ACCEPTED,REJECTED" if pool == "validation_exam" else "SUBMITTED,ACCEPTED"
        answers = api.list("assignments", pool_id=api.get("pool:" + pool)["id"], status=statuses)
        updates = sum(api.record_assignment(pool, answer) for answer in answers)
        changed += updates
        event("pool.polled", pool=pool, received=len(answers), updated=updates)
    return changed


def cycle(api, *, refresh=True):
    changed = fetch(api)
    released = release_expired_work_skills(api, CONFIG["work_quality"]["ban_below"])
    if changed or refresh or released:
        route(api)
        process(api)
    open_ready_pools(api)
    results = api.review_state / "results.json"
    rows = json.loads(results.read_text()) if results.exists() else []
    states = dict(Counter(row["status"] for row in rows))
    output = api.review_state / "golden.jsonl"
    selected = json.loads((api.review_state / "selection.json").read_text())
    finished = states.get("FINAL", 0) == len(rows) == len(selected)
    if finished:
        export_golden(api.review_state, output)
    elif output.exists():
        output.unlink()
    return {
        "updated_assignments": changed,
        "selected_photos": len(selected),
        "photos": states,
        "exported": finished,
    }


class JsonFormatter(logging.Formatter):
    def format(self, record):
        timestamp = datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="seconds")
        return json.dumps(
            {
                "time": timestamp,
                "level": record.levelname,
                "event": record.getMessage(),
                **getattr(record, "fields", {}),
            },
            ensure_ascii=False,
        )


def run(api, interval):
    log = RotatingFileHandler(
        api.state / "worker.jsonl", maxBytes=10_000_000, backupCount=3, encoding="utf-8"
    )
    log.setFormatter(JsonFormatter())
    logger = logging.getLogger("butterfly.worker")
    logger.setLevel(logging.INFO)
    logger.addHandler(log)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    previous_version = None
    failures = 0
    try:
        while not stop.is_set():
            started = monotonic()
            try:
                with pipeline_lock(api.state):
                    version = api.db.execute("PRAGMA data_version").fetchone()[0]
                    report = cycle(api, refresh=version != previous_version)
                    previous_version = version
                failures = 0
                delay = interval
                event("cycle.finished", duration_seconds=round(monotonic() - started, 2), **report)
            except Exception as exc:
                failures += 1
                previous_version = None
                delay = min(900, interval * 2 ** min(failures - 1, 8))
                report = {"error": str(exc).splitlines()[0][:500], "type": type(exc).__name__}
                event("cycle.failed", level=logging.ERROR, **report)
            report["time"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            report["next_poll_seconds"] = delay
            save_json(api.state / "status.json", report)
            print(json.dumps(report, ensure_ascii=False), flush=True)
            stop.wait(delay)
    finally:
        logger.removeHandler(log)
        log.close()
