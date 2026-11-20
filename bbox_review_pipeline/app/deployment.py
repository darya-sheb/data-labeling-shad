"""Create platform resources in dependency order. Each object has a stable local key."""

import base64
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .api import ROOT, save_json
from .materials import (
    CONFIG,
    bbox_input,
    control_pages,
    load,
    model_record,
    photos_for_review,
    practice_task,
    validation_focus_tasks,
    validation_queue,
)
from .models import review_suite

TITLES = {
    "annotation_quality": "Бабочки: качество разметки",
    "annotation_work_quality": "Бабочки: качество работы",
    "validation_quality": "Бабочки: качество проверки",
}


def projects():
    folder = ROOT / "interfaces"
    specs = json.loads((folder / "projects.json").read_text())
    for role, project in specs.items():
        directory = folder / role
        project["public_instructions"] = (directory / "instructions.html").read_text().strip()
        view = project["task_spec"]["view_spec"]
        script = (folder / "zoom.js").read_text() + "\n" + (directory / "task.js").read_text()
        if role == "bbox":
            movie = base64.b64encode((ROOT / "media/annotation.mp4").read_bytes()).decode()
            script = script.replace("__BF_GUIDE_MP4__", movie)
            script = (directory / "bootstrap.js").read_text().replace("__TASK_SCRIPT__", script)
        view.update(
            markup=(directory / "template.html").read_text(),
            styles=(directory / "styles.css").read_text(),
            script=script,
        )
    return specs


def resolve(value, api):
    """Substitute this installation's IDs and settings into pool templates."""
    if isinstance(value, list):
        return [resolve(v, api) for v in value]
    if isinstance(value, dict):
        return {k: resolve(v, api) for k, v in value.items()}
    if isinstance(value, str) and value.startswith("@settings:"):
        setting = CONFIG
        for key in value.split(":")[1:]:
            setting = setting[key]
        return setting
    if isinstance(value, str) and value.startswith("@"):
        return api.get(value[1:])["id"]
    return value


def setup(api):
    path = api.review_state / "installation.json"
    if path.exists():
        install = json.loads(path.read_text())
    else:
        expires = datetime.now(timezone.utc) + timedelta(days=CONFIG["pool_lifetime_days"])
        install = {
            "id": uuid4().hex[:12],
            "expires": expires.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        }
        save_json(path, install)
    for key, title in TITLES.items():
        api.create(
            "skill:" + key,
            "skills",
            {
                "name": f"{title} {install['id']}",
                "public_name": {"RU": title, "EN": title},
                "public_requester_description": {"RU": title, "EN": title},
                "hidden": False,
            },
        )
    for role, spec in projects().items():
        api.create("project:" + role, "projects", spec)
    templates = load("pools")
    for role, spec in templates["trainings"].items():
        api.create("training:" + role, "trainings", resolve(spec, api))
    for name, template in templates["pools"].items():
        spec = resolve(template, api)
        spec.update(will_expire=install["expires"], reward_per_assignment=CONFIG["rewards_rub"][name])
        api.create("pool:" + name, "pools", spec)
    seed_tasks(api)
    stage_model_reviews(api)


def seed_tasks(api):
    training = api.get("training:bbox")["id"]
    for r in load("bbox_training"):
        api.create("task:bbox_training:" + r["image_id"], "tasks", practice_task(r, training))
    for task in validation_focus_tasks():
        api.create(
            "task:validation_training:" + task["input_values"]["review_item_id"],
            "tasks",
            {**task, "pool_id": api.get("training:validation")["id"], "infinite_overlap": True},
        )
    exams = [
        ("bbox_qualification", "exam10", [{"input_values": bbox_input(r)} for r in load("bbox_exam")]),
        ("validation_exam", "1", load("validation_exam")),
    ]
    for name, suffix, tasks in exams:
        api.create(
            f"suite:{name}:{suffix}",
            "task-suites",
            {
                "pool_id": api.get("pool:" + name)["id"],
                "tasks": tasks,
                "mixed": False,
                "overlap": CONFIG["exam_participants"][name],
                "infinite_overlap": False,
            },
        )


def stage_model_reviews(api):
    receipt = api.review_state / "selection.json"
    if receipt.exists():
        return
    photos = photos_for_review()
    queue = validation_queue(api, "validation_production", control_pages())
    for photo in photos:
        queue.create_review(
            "suite:review:model:" + photo["image_id"],
            review_suite(queue.pool, model_record(photo), CONFIG["validation_overlap"]),
        )
    save_json(receipt, [photo["image_id"] for photo in photos])
