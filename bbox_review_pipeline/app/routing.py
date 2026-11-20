"""Route submitted boxes to independent reviewers and create eligible corrections."""

import json

from .annotation_exam import compare_exam_photo
from .api import APIError, save_json
from .materials import (
    CONFIG,
    bbox_input,
    control_pages,
    exam_references,
    validation_queue,
)
from .models import candidates, from_annotation, review_suite
from .validation_quality import (
    blocking_reviewers,
    correction_rejections,
    validation_submissions,
)
from .work_quality import utc
from .worker_log import event


def conflicting_corrections(api, rejections=None):
    conflicts = {}
    rows = api.db.execute("""SELECT id, json_extract(data,'$.task_suite_id'), json_extract(data,'$.user_id'),
        json_extract(data,'$.tasks[0].input_values.image_url'), json_extract(data,'$.tasks[0].input_values.revision'),
        json_extract(data,'$.submitted') FROM assignments WHERE pool_key='bbox_production'
        AND json_type(data,'$.tasks[0].input_values.revision')='integer' AND json_extract(data,'$.tasks[0].input_values.revision')>1""").fetchall()
    if rows and rejections is None:
        rejections = correction_rejections(validation_submissions(api))
    for identity, suite_id, worker, photo, revision, submitted in rows:
        if worker in blocking_reviewers(rejections, photo, revision, utc(submitted) if submitted else None):
            conflicts[identity] = suite_id
    return conflicts


def route(api):
    """Actual author IDs come exclusively from API assignments, never from submitted form inputs."""
    controls = control_pages()
    references = exam_references()
    queues = {}
    invalid = {}
    conflicts = conflicting_corrections(api)
    report = api.review_state / "invalid_annotations.json"
    previous = json.loads(report.read_text()) if report.exists() else {}
    lineage_path = api.review_state / "lineage.json"
    lineage = json.loads(lineage_path.read_text()) if lineage_path.exists() else {}
    lineage_changed = False
    for pool, raw in api.db.execute(
        'SELECT pool_key,data FROM assignments WHERE pool_key IN ("bbox_production","bbox_qualification") ORDER BY rowid'
    ).fetchall():
        a = json.loads(raw)
        try:
            if a["id"] in conflicts:
                raise ValueError("This worker previously rejected the same photograph as a validator")
            if (
                not a.get("user_id")
                or not a.get("tasks")
                or len(a["tasks"]) != len(a["solutions"])
                or (pool == "bbox_production" and len(a["tasks"]) != 1)
            ):
                raise ValueError("Invalid annotation assignment")
            parsed = []
            for task, solution in zip(a["tasks"], a["solutions"]):
                values = task["input_values"]
                if not (
                    values["image_id"]
                    and values["image_url"]
                    and type(values["revision"]) is int
                    and isinstance(values["fixed_boxes"], list)
                ):
                    raise ValueError("Invalid source photo")
                submitted_boxes = solution["output_values"]["result"]
                if not isinstance(submitted_boxes, list):
                    raise ValueError("Missing rectangle list")
                parsed.append([from_annotation(x) for x in submitted_boxes])
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            invalid[a["id"]] = {"pool": pool, "reason": str(exc)}
            if previous.get(a["id"]) != invalid[a["id"]]:
                event("annotation.invalid", assignment_id=a["id"], pool=pool, reason=str(exc))
            continue
        for index, (task, boxes) in enumerate(zip(a["tasks"], parsed)):
            routing_id = a["id"] + ("_" + str(index) if len(a["tasks"]) > 1 else "")
            v = task["input_values"]
            # The assignment ID separates different workers taking the same qualification image.
            image_id = v["image_id"] + ("_exam_" + a["id"] if pool == "bbox_qualification" else "")
            authors = set([a["user_id"]])
            authors.update(lineage.get(v["image_id"], []))
            if pool == "bbox_production" and lineage.get(v["image_id"]) != sorted(authors):
                lineage[v["image_id"]] = sorted(authors)
                lineage_changed = True
            r = {
                "image_id": image_id,
                "source_image_id": v["image_id"],
                "image_url": v["image_url"],
                "revision": v["revision"],
                "fixed_boxes": v["fixed_boxes"],
                "candidate_boxes": candidates(image_id, v["revision"], boxes),
                "source_annotation_worker_ids": sorted(authors),
                "annotation_assignment_id": a["id"],
                "annotation_task_index": index,
                "annotation_worker_id": a["user_id"],
                "qualification": pool == "bbox_qualification",
            }
            output = a["solutions"][index]["output_values"]
            r["empty_confirmed"] = output.get("reviewed") is True and output.get("empty_confirmed") is True
            receipt = api.review_state / ("review_" + routing_id + ".json")
            key = "suite:review:" + routing_id
            comparison = None
            if r["qualification"]:
                if receipt.exists():
                    continue
                comparison = compare_exam_photo(v, output, boxes, references.get(v["image_id"]))
                if comparison is not None:
                    r["reference_count"] = comparison["reference_count"]
                if comparison and comparison["score"] is not None:
                    save_json(receipt, {"record": r, "exam_iou": comparison})
                    event(
                        "exam.photo_auto_graded", assignment_id=a["id"], image_id=v["image_id"], **comparison
                    )
                    continue
            target = "validation_annotation_exam" if r["qualification"] else "validation_production"
            overlap = CONFIG["validation_overlap"]
            payload = review_suite(api.get("pool:" + target)["id"], r, overlap)
            if target not in queues:
                queues[target] = validation_queue(api, target, controls)
            created = queues[target].create_review(key, payload)
            # Later revisions may add authors. Replay the exclusions of this exact page.
            r["source_annotation_worker_ids"] = created["unavailable_for"]
            review = {"record": r, "suite_id": created["id"]}
            if comparison is not None:
                review["exam_iou"] = comparison
            save_json(receipt, review)
            event(
                "annotation.routed",
                assignment_id=a["id"],
                image_id=image_id,
                revision=v["revision"],
                destination=target,
                suite_id=created["id"],
                boxes=len(boxes),
                overlap=created["overlap"],
                excluded_authors=len(r["source_annotation_worker_ids"]),
            )
    if lineage_changed:
        save_json(lineage_path, lineage)
    if invalid != previous:
        save_json(report, invalid)


def correction_input(record, result):
    inputs = bbox_input(
        {
            "image_id": record["image_id"],
            "image_url": record["image_url"],
            "boxes": result["editable_boxes"],
            "fixed_boxes": result["fixed_boxes"],
        },
        revision=record["revision"] + 1,
    )
    if result.get("correction_feedback"):
        inputs["correction_feedback"] = result["correction_feedback"]
    return inputs


def archive_correction(api, key, page):
    with api.db:
        api.db.execute(
            "UPDATE objects SET key=? WHERE key=?", ("history:withdrawn:" + page["id"] + ":" + key, key)
        )
    api.save_manifest()


def withdraw_unclaimed_correction(api, key, page):
    """The platform preserves claimed places when reducing overlap."""
    if not page["overlap"]:
        return True
    if api.db.execute(
        "SELECT 1 FROM assignments WHERE json_extract(data,'$.task_suite_id')=?", (page["id"],)
    ).fetchone() or any(
        a.get("task_suite_id") == page["id"]
        for a in api.list("assignments", pool_id=page["pool_id"], status="ACTIVE,SUBMITTED,ACCEPTED")
    ):
        return False
    remaining = api.patch_suite_overlap(key, 0)["overlap"]
    event("correction.withdrawn", suite_id=page["id"], remaining=remaining)
    return remaining == 0


def reconcile_correction(api, record, result):
    """Withdraw stale unissued corrections. Submitted revisions receive their own independent reviews."""
    key = f"suite:reannotation:{record['image_id']}:{record['revision'] + 1}"
    row = api.db.execute("SELECT response FROM objects WHERE key=? AND status='DONE'", (key,)).fetchone()
    if not row:
        return
    page = json.loads(row[0])
    needed = result["status"] == "NEEDS_ANNOTATION"
    same = needed and page["tasks"][0]["input_values"] == correction_input(record, result)
    if same:
        return
    if not withdraw_unclaimed_correction(api, key, page):
        return
    if needed:
        archive_correction(api, key, page)


def correction_page(api, record, result, *, rejections=None, conflicted_suites=(), admitted=None):
    """Queue a production correction within the limit for the source photograph."""
    revision = record["revision"] + 1
    if rejections is None:
        rejections = correction_rejections(validation_submissions(api))
    reviewers = blocking_reviewers(rejections, record["image_url"], revision)
    unavailable = set(record["source_annotation_worker_ids"]) | reviewers
    key = "suite:reannotation:" + record["image_id"] + ":" + str(revision)
    existing = api.db.execute("SELECT response,status FROM objects WHERE key=?", (key,)).fetchone()
    if existing:
        if existing[1] != "DONE":
            raise APIError("Reconcile pending correction before continuing: " + key)
        page = json.loads(existing[0])
        ineligible_submission = page["id"] in conflicted_suites
        if (
            admitted is not None
            and not (admitted - unavailable - set(page.get("unavailable_for", [])))
            and not ineligible_submission
        ):
            unavailable.update(page.get("unavailable_for", []))
            if page["overlap"]:
                page = api.patch_suite_overlap(key, 0)
                if page["overlap"]:
                    return page  # The platform preserved an issued assignment.
        if ineligible_submission or not unavailable.issubset(page.get("unavailable_for", [])):
            # Task-suite eligibility is set at creation. Withdraw unissued places before replacing a page.
            if (
                page["overlap"]
                and not ineligible_submission
                and api.db.execute(
                    "SELECT 1 FROM assignments WHERE json_extract(data,'$.task_suite_id')=?", (page["id"],)
                ).fetchone()
            ):
                return page
            if page["overlap"]:
                page = api.patch_suite_overlap(key, 0)
            if page["overlap"] and not ineligible_submission:
                return page  # A worker already claimed it. Check their identity when the answer arrives.
            unavailable.update(page.get("unavailable_for", []))
            archive_correction(api, key, page)
            existing = None
            event(
                "correction.exclusions_updated",
                suite_id=page["id"],
                image_id=record["image_id"],
                excluded_reviewers=len(reviewers),
                conflicted_submission=ineligible_submission,
            )
        elif page["overlap"]:
            return page
    count = 0
    for (raw,) in api.db.execute(
        'SELECT payload FROM objects WHERE key LIKE "suite:reannotation:%" OR key LIKE "history:%:suite:reannotation:%"'
    ):
        page = json.loads(raw)
        tasks = page.get("tasks", [])
        if page.get("overlap", 0) and tasks and tasks[0]["input_values"]["image_url"] == record["image_url"]:
            count += 1
    limit = CONFIG["max_reannotations_per_image"]
    if count >= limit:
        return None
    if admitted is not None and not (admitted - unavailable):
        result.update(
            status="NO_ELIGIBLE_ANNOTATOR",
            unavailable_for=sorted(unavailable),
            reason="No admitted annotator is eligible to correct this photo.",
        )
        return None
    if existing:
        return api.patch_suite_overlap(key, 1)
    suite = api.create(
        key,
        "task-suites",
        {
            "pool_id": api.get("pool:bbox_production")["id"],
            "tasks": [{"input_values": correction_input(record, result)}],
            "mixed": False,
            "overlap": 1,
            "infinite_overlap": False,
            "unavailable_for": sorted(unavailable),
        },
    )
    event(
        "correction.created",
        suite_id=suite["id"],
        image_id=record["image_id"],
        revision=revision,
        excluded_reviewers=len(reviewers),
        excluded_total=len(unavailable),
    )
    lineage_path = api.review_state / "lineage.json"
    lineage = json.loads(lineage_path.read_text()) if lineage_path.exists() else {}
    lineage[record["image_id"]] = sorted(
        set(lineage.get(record["image_id"], []) + record["source_annotation_worker_ids"])
    )
    save_json(lineage_path, lineage)
    return suite
