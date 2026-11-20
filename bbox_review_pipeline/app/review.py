"""Rebuild each photo from independent ballots and any recorded whole-photo acceptance."""

import json
import math
from collections import defaultdict
from datetime import datetime, timezone

from .api import save_json
from .materials import CONFIG, control_pages, model_reviews, validation_queue
from .models import (
    accepted_frames,
    aggregate,
    confirmed_empty_photo,
    exam_photo_score,
    item_decisions,
    review_tasks,
    work_photo_score,
)
from .revision_review import (
    admitted_annotators,
    corrected_scene,
    fingerprint,
    select_scene,
)
from .routing import (
    conflicting_corrections,
    correction_page,
    reconcile_correction,
    withdraw_unclaimed_correction,
)
from .validation_quality import (
    correction_rejections,
    validation_ballots,
    validation_submissions,
    validator_exams,
)
from .work_quality import apply_work_quality, utc
from .worker_log import event


def resolve_review(api, record, suite_id, votes, received, minimum, pending):
    decisions = item_decisions(record, votes, minimum)
    waiting = [item for item, d in decisions.items() if d["status"] == "WAITING_VOTES"]
    if suite_id and waiting:
        pending.append(
            {
                "suite_id": suite_id,
                "image_url": record["image_url"],
                "tasks": [
                    t["input_values"]
                    for t in review_tasks(record)
                    if t["input_values"]["review_item_id"] in waiting
                ],
            }
        )
        update_overlap(api, suite_id, waiting, received, minimum)
    return decisions


def update_overlap(api, suite_id, waiting, received, minimum):
    """Only buy an additional ballot when the existing submissions are insufficient."""
    row = api.db.execute(
        """SELECT key, json_extract(payload,'$.overlap') FROM objects WHERE
        kind='task-suites' AND status='DONE' AND id=? AND key LIKE 'suite:review:%'""",
        (suite_id,),
    ).fetchone()
    if row:
        key, overlap = row
        limit = CONFIG["max_review_overlap"]
        if 0 < overlap < minimum:
            target = min(limit, max(minimum, received + 1))
            api.patch_suite_overlap(key, target)
            event("validation.quorum_restored", suite_id=suite_id, overlap=target)
        elif 0 < overlap <= received and overlap < limit:
            api.patch_suite_overlap(key, overlap + 1)
            event(
                "validation.additional_vote_requested",
                suite_id=suite_id,
                overlap=overlap + 1,
                submissions=received,
                unresolved=waiting,
            )


def score_annotator(record, original, decisions, result, empty_photo, empty_reports):
    """A confirmed coverage error contributes to the worker's rolling quality score."""
    score = None
    if not record["qualification"] and record is original and record.get("annotation_assignment_id"):
        score = work_photo_score(record, decisions, result)
        if empty_photo and record.get("annotation_worker_id"):
            coverage = decisions[f"{record['image_id']}_r{record['revision']}_coverage"]
            if coverage["missing_reported_by"]:
                disposition = {"missing_yes": "confirmed", "missing_no": "overruled"}.get(
                    coverage["answer"], "pending"
                )
                empty_reports[record["annotation_worker_id"]][record["annotation_assignment_id"]] = {
                    "photo": record["image_id"],
                    "revision": record["revision"],
                    "status": disposition,
                    "reported_by": coverage["missing_reported_by"],
                    "score": score,
                }
    return score


def process(api, now=None):
    """Evaluate parent revisions first so changes to a parent invalidate stale child reviews."""
    now = now or datetime.now(timezone.utc)
    minimum = CONFIG["validation_overlap"]
    if type(minimum) is not int or minimum < 2:
        raise ValueError("validation_overlap must be at least 2 for independent review")
    if CONFIG["max_review_overlap"] < minimum + 1:
        raise ValueError("max_review_overlap must allow at least one deciding vote")
    api.db.execute("CREATE TABLE IF NOT EXISTS review_scenes (base TEXT PRIMARY KEY, active_key TEXT)")
    api.db.execute("CREATE TABLE IF NOT EXISTS photo_acceptances (id TEXT PRIMARY KEY)")
    queue = None

    def production_queue():
        nonlocal queue
        if queue is None:
            queue = validation_queue(api, "validation_production", control_pages())
        return queue

    submissions = list(validation_submissions(api))
    rejections = correction_rejections(submissions)
    conflicts = conflicting_corrections(api, rejections)
    conflicted_suites = set(conflicts.values()) - {None}
    suite_votes, received, _ = validation_ballots(
        api, CONFIG, api.review_state / "validator_controls.json", now, submissions=submissions
    )
    pending = []
    exam_items = defaultdict(dict)
    work_scores = {}
    empty_reports = defaultdict(dict)
    latest = {}
    correction_requests = {}
    rejected = defaultdict(set)
    reviews = [json.loads(path.read_text()) for path in sorted(api.review_state.glob("review_*.json"))]
    reviews = [r for r in reviews if r["record"].get("annotation_assignment_id")]
    reviews.extend(model_reviews(api))
    for review in sorted(reviews, key=lambda r: r["record"]["revision"]):
        original = record = review["record"]
        source = record.get("source_image_id", record["image_id"])
        suite_id = review.get("suite_id")
        comparison = review.get("exam_iou")
        if record["qualification"] and comparison and comparison["score"] is not None:
            exam_items[record["annotation_assignment_id"]][record["annotation_task_index"]] = {
                "source_image_id": source,
                "worker_id": record["annotation_worker_id"],
                "review_complete": True,
                "status": "EXAM_REVIEWED",
                "method": "iou",
                **comparison,
            }
            continue
        if record.get("annotation_assignment_id") in conflicts:
            select_scene(api, suite_id, original, None, received, production_queue, minimum)
            reconcile_correction(api, record, {"status": "WAITING_VALIDATION"})
            continue
        if (
            not record["qualification"]
            and source in latest
            and latest[source]["revision"] < record["revision"]
        ):
            parent = latest[source]
            if parent["status"] == "WAITING_VALIDATION" or parent["revision"] != record["revision"] - 1:
                select_scene(api, suite_id, original, None, received, production_queue, minimum)
                reconcile_correction(api, record, {"status": "WAITING_VALIDATION"})
                if parent["revision"] != record["revision"] - 1:
                    # A conflicted intermediate submission was discarded. Keep its parent
                    # actionable so an eligible annotator can repair it.
                    continue
                latest[source] = {
                    "image_id": record["image_id"],
                    "source_image_id": source,
                    "image_url": record["image_url"],
                    "revision": record["revision"],
                    "status": "WAITING_VALIDATION",
                    "fixed_boxes": [],
                    "editable_boxes": [],
                    "decisions": {},
                    "waiting_for_revision": parent.get("waiting_for_revision", parent["revision"]),
                }
                continue
            record = corrected_scene(original, parent)
            suite_id = select_scene(api, suite_id, original, record, received, production_queue, minimum)
        votes = suite_votes[suite_id]
        decisions = resolve_review(api, record, suite_id, votes, received[suite_id], minimum, pending)
        empty_photo = confirmed_empty_photo(record) or (
            record is not original and not record["fixed_boxes"] and not record["candidate_boxes"]
        )
        result = aggregate(record, decisions)
        score = score_annotator(record, original, decisions, result, empty_photo, empty_reports)
        if not record["qualification"]:
            reconcile_correction(api, record, result)
        if record["qualification"]:
            score = exam_photo_score(record, decisions)
            review_complete = score is not None
            result["status"] = "EXAM_REVIEWED" if review_complete else "WAITING_VALIDATION"
            result["score"] = score
            exam_items[record["annotation_assignment_id"]][record["annotation_task_index"]] = {
                "source_image_id": record["source_image_id"],
                "worker_id": record["annotation_worker_id"],
                "score": score,
                "status": result["status"],
                "decisions": decisions,
                "review_complete": review_complete,
            }
            if comparison:
                exam_items[record["annotation_assignment_id"]][record["annotation_task_index"]].update(
                    method="validators", **{k: v for k, v in comparison.items() if k != "score"}
                )
        if not record["qualification"] and score is not None and record.get("annotation_assignment_id"):
            work_scores[record["annotation_assignment_id"]] = score
        if not record["qualification"]:
            if source not in latest or latest[source]["revision"] < result["revision"]:
                initial_source = latest.get(source, {}).get("initial_source", record.get("source", "human"))
                latest[source] = {
                    **result,
                    "initial_source": initial_source,
                    "source_image_id": source,
                    "image_url": record["image_url"],
                    "decisions": decisions,
                    "source_annotation_worker_ids": record.get("source_annotation_worker_ids", []),
                }
                if result["status"] == "NEEDS_ANNOTATION":
                    correction_requests[source] = (record, suite_id)
                    if any(d["answer"] in ("bad_geometry", "missing_yes") for d in decisions.values()):
                        rejected[source].add(record["revision"])
        event(
            "review.evaluated",
            image_id=record["image_id"],
            revision=record["revision"],
            suite_id=suite_id,
            status=result["status"],
            removed_duplicates=result["removed_duplicates"],
            decisions={
                key: {"answer": d["answer"], "votes": d["vote_count"], "status": d["status"]}
                for key, d in decisions.items()
            },
        )
    save_json(api.review_state / "pending_validation.json", pending)
    save_json(api.review_state / "work_quality_empty_reports.json", empty_reports)
    save_json(api.review_state / "validation_exam_acceptance.json", validator_exams(api, CONFIG))
    grade_annotation_exams(api, exam_items)
    apply_work_quality(api, work_scores, CONFIG["work_quality"], now)
    publish_results(api, latest, correction_requests, rejections, conflicted_suites, rejected)


def grade_annotation_exams(api, exam_items):
    """Pay completed submissions and grant admission using all ten photo scores."""
    exam_report = []
    quality_by_worker = {}
    for assignment_id, items in exam_items.items():
        row = api.db.execute(
            'SELECT data FROM assignments WHERE id=? AND pool_key="bbox_qualification"', (assignment_id,)
        ).fetchone()
        if not row:
            raise ValueError("Missing source exam assignment: " + assignment_id)
        source = json.loads(row[0])
        complete = (
            len(source["tasks"]) == CONFIG["qualification_images"]
            and set(items) == set(range(len(source["tasks"])))
            and all(
                v["review_complete"]
                and v["worker_id"] == source["user_id"]
                and v["source_image_id"] == source["tasks"][i]["input_values"]["image_id"]
                for i, v in items.items()
            )
        )
        grade = (
            round(math.fsum(v["score"] for v in items.values()) / len(items), 10)
            if complete and all(v["score"] is not None for v in items.values())
            else None
        )
        passed = grade >= CONFIG["annotation_threshold"] if grade is not None else None
        status = "ACCEPTED" if source["status"] == "ACCEPTED" else "WAITING_VALIDATION"
        if complete and status != "ACCEPTED":
            status = api.accept_exam(assignment_id)["status"]
        issued = source.get("created") or source.get("started")
        duration = (
            (utc(source["submitted"]) - utc(issued)).total_seconds()
            if issued and source.get("submitted")
            else None
        )
        fast = 0 <= duration < CONFIG["exam_fast_report_seconds"] if duration is not None else None
        event(
            "exam.evaluated",
            assignment_id=assignment_id,
            complete=complete,
            status=status,
            score=grade,
            duration_seconds=duration,
            fast_submission=fast,
        )
        exam_report.append(
            {
                "assignment_id": assignment_id,
                "review_complete": complete,
                "payment_status": status,
                "score": grade,
                "passed": passed,
                "duration_seconds": duration,
                "fast_submission": fast,
                "photos": [items[i] for i in sorted(items)],
            }
        )
        if grade is not None:
            # The API stores three decimals; rounding a near miss must not open the work pool.
            quality_by_worker[source["user_id"]] = (
                grade if passed else min(grade, CONFIG["annotation_threshold"] - 0.001)
            )
        elif source["status"] == "ACCEPTED":
            # A paid exam can return to review after a validator fails a control.
            # Suspend a previously granted admission until its replacement votes arrive.
            prev = api.db.execute("SELECT 1 FROM sqlite_master WHERE name='applied_skills'").fetchone()
            if (
                prev
                and api.db.execute(
                    "SELECT 1 FROM applied_skills WHERE skill_id=? AND user_id=?",
                    (api.get("skill:annotation_quality")["id"], source["user_id"]),
                ).fetchone()
            ):
                quality_by_worker[source["user_id"]] = 0
    save_json(api.review_state / "exam_acceptance.json", exam_report)
    for worker, grade in quality_by_worker.items():
        api.assign_skill("annotation_quality", worker, grade)


def publish_results(api, latest, correction_requests, rejections, conflicted_suites, rejected):
    """Route unfinished photos and publish one current revision per source image."""
    admitted = admitted_annotators(api, CONFIG)
    queue = []
    approvals = {row[0] for row in api.db.execute("SELECT id FROM photo_acceptances")}
    for source, result in latest.items():
        if result["status"] != "NEEDS_ANNOTATION":
            continue
        record, suite_id = correction_requests[source]
        frames = accepted_frames(record, result, rejected[source])
        acceptance_id = (
            fingerprint([suite_id, sorted(rejected[source]), frames, result["decisions"]]) if frames else None
        )
        if acceptance_id in approvals:
            result.update(status="FINAL", fixed_boxes=frames, editable_boxes=[], accepted_as_is=True)
            reconcile_correction(api, record, result)
            continue
        page = correction_page(
            api, record, result, rejections=rejections, conflicted_suites=conflicted_suites, admitted=admitted
        )
        if page:
            result["reannotation_suite_id"] = page["id"]
        elif result["status"] == "NEEDS_ANNOTATION":
            result.update(
                status="REANNOTATION_LIMIT_REACHED",
                reason=f"Correction limit per source image reached ({CONFIG['max_reannotations_per_image']}).",
            )
        if acceptance_id:
            queue.append(
                {
                    "acceptance_id": acceptance_id,
                    "photo_id": source,
                    "revision": record["revision"],
                    "rejected_revisions": sorted(rejected[source]),
                    "image_url": record["image_url"],
                    "boxes": [frame["bbox"] for frame in frames],
                    "next_correction_suite": page["id"] if page else None,
                }
            )
    save_json(api.review_state / "results.json", list(latest.values()))
    save_json(api.review_state / "acceptance_queue.json", queue)


def accept_photo(api, acceptance_id):
    """Record consent for exactly one reviewed scene. The worker rechecks it on its next cycle."""
    queue = api.review_state / "acceptance_queue.json"
    if not queue.exists():
        raise ValueError("Очередь приёмки ещё не сформирована.")
    if api.db.execute("SELECT 1 FROM photo_acceptances WHERE id=?", (acceptance_id,)).fetchone():
        return
    entry = next((x for x in json.loads(queue.read_text()) if x["acceptance_id"] == acceptance_id), None)
    if entry is None:
        raise ValueError("Эта версия не ожидает приёмки.")
    if entry["next_correction_suite"]:
        key = f"suite:reannotation:{entry['photo_id']}:{entry['revision'] + 1}"
        page = api.get(key)
        if page["id"] != entry["next_correction_suite"] or not withdraw_unclaimed_correction(api, key, page):
            raise ValueError("Следующее исправление уже выдано или страница изменилась. Дождитесь проверки.")
    with api.db:
        api.db.execute("INSERT INTO photo_acceptances VALUES (?)", (acceptance_id,))
    event("photo.accepted_as_is", image_id=entry["photo_id"], revision=entry["revision"])
