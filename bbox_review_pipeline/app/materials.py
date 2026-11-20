"""Training materials, controls and production task inputs."""

import json

from .api import ROOT
from .models import annotation, candidates, review_tasks, validation_solutions
from .validation_controls import ValidationQueue


def load(name):
    return json.loads((ROOT / "data" / (name + ".json")).read_text())


def photos_for_review():
    """Use the supplied model boxes and the majority result from three earlier votes."""
    return [photo for photo in load("photos") if photo["boxes"] or photo["filter_yes"] >= 2]


CONFIG = json.loads((ROOT / "config.json").read_text())


def bbox_input(record, practice=False, revision=1, fixed=()):
    fixed = record.get("fixed_boxes", fixed)
    result = {
        "image_id": record["image_id"],
        "image_url": record["image_url"],
        "display_image_url": record["image_url"],
        "revision": revision,
        "editable_annotations": [annotation(b) for b in record.get("initial_boxes", [])]
        if practice
        else [annotation(b) for b in record["boxes"]],
        "fixed_boxes": list(fixed),
        "practice": practice,
    }
    if practice:
        result.update(reference_boxes=record["boxes"], iou_threshold=CONFIG["practice_iou_threshold"])
    return result


def validation_focus_tasks():
    lesson = load("validation_lesson")
    record = {
        "image_id": lesson["image_id"],
        "image_url": lesson["image_url"],
        "revision": 1,
        "fixed_boxes": [
            {"box_id": lesson["image_id"] + "_fixed", "bbox": lesson["reference_boxes"]["lower"]}
        ],
        "candidate_boxes": [],
    }
    for i, frame in enumerate(lesson["frames"]):
        bbox = frame["bbox"] if "bbox" in frame else lesson["reference_boxes"][frame["butterfly"]]
        record["candidate_boxes"].append({"box_id": f"{lesson['image_id']}_b{i}", "bbox": bbox})
    # The fixed reference stays visible throughout, without a question of its own.
    tasks = review_tasks(record)
    for task, step in zip(tasks, [*lesson["frames"], lesson["coverage"]], strict=True):
        answer, hint = step["answer"], step["hint"]
        values = task["input_values"]
        expected = answer
        if answer == "duplicate":
            expected += ":" + step["reason"]
        values.update(training=True, expected_answer=expected, training_hint=hint)
        solution = {"answer": answer}
        if "reason" in step:
            solution["duplicate_reason"] = step["reason"]
        task["known_solutions"] = [{"output_values": solution, "correctness_weight": 1}]
        task["message_on_unknown_solution"] = hint
    return tasks


def practice_task(r, pool_id):
    if r.get("confirm_empty"):
        # The production editor exposes the real empty checkbox. The native
        # training pool grades it directly, without an IoU reference.
        return {
            "pool_id": pool_id,
            "input_values": bbox_input(r),
            "known_solutions": [
                {
                    "output_values": {
                        "result": [],
                        "empty_confirmed": True,
                        "reviewed": True,
                        "practice_passed": False,
                    },
                    "correctness_weight": 1,
                }
            ],
            "message_on_unknown_solution": "На фото только трава. Удалите рамки, отметьте «Добавлять рамки не нужно» и подтвердите, что просмотрели всё фото.",
            "infinite_overlap": True,
        }
    return {
        "pool_id": pool_id,
        "input_values": bbox_input(r, True),
        "known_solutions": [
            {"output_values": {"reviewed": True, "practice_passed": True}, "correctness_weight": 1}
        ],
        "message_on_unknown_solution": f"Исправьте или добавьте рамку вокруг бабочки без фиксированной рамки. Нужно совпадение не менее {round(CONFIG['practice_iou_threshold'] * 100)}%. Подтвердите просмотр и нажмите Enter для сравнения с синим ориентиром.",
        "infinite_overlap": True,
    }


def model_reviews(api):
    # The original issued inputs in the journal survive restarts and preserve the model baseline.
    for suite, raw in api.db.execute("""SELECT id,payload FROM objects WHERE key LIKE 'suite:review:model:%'
            AND status='DONE' AND json_extract(payload,'$.pool_id')=
                (SELECT id FROM objects WHERE key='pool:validation_production')"""):
        values = [t["input_values"] for t in json.loads(raw)["tasks"]]
        record = model_record(
            {
                "image_id": values[0]["image_id"],
                "image_url": values[0]["image_url"],
                "boxes": [v["focus_bbox"] for v in values if v["review_type"] == "box"],
            }
        )
        yield {"record": record, "suite_id": suite}


def model_record(photo):
    image = photo["image_id"]
    return {
        **photo,
        "revision": 1,
        "source": "model",
        "source_image_id": image,
        "qualification": False,
        "candidate_boxes": candidates(image, 1, photo["boxes"]),
        "fixed_boxes": [],
        "source_annotation_worker_ids": [],
    }


def exam_references():
    return {
        r["image_id"]: {**r, "editable_annotations": [annotation(b) for b in r["boxes"]]}
        for r in load("bbox_exam")
    }


def control_pages():
    pages = []
    for photo in load("validation_controls"):
        frames = photo["frames"]
        record = {
            **photo,
            "revision": 1,
            "fixed_boxes": [b for b in frames if b["fixed"]],
            "candidate_boxes": [b for b in frames if not b["fixed"]],
        }
        page = review_tasks(record)
        for task, answer in zip(page, photo["answers"], strict=True):
            task["known_solutions"] = validation_solutions(answer)
        pages.append(page)
    return pages


def validation_queue(api, target, controls):
    limit = CONFIG["exam_control_page_limit"] if target == "validation_annotation_exam" else None
    return ValidationQueue(
        api,
        target,
        controls,
        CONFIG["validation_control_interval"],
        CONFIG["validation_control_overlap"],
        page_limit=limit,
    )
