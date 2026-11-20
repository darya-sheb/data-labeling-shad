"""Keep reviews bound to the scene their validators actually saw."""

import hashlib
import json

from .models import review_suite
from .worker_log import event


def fingerprint(value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode()).hexdigest()


def corrected_scene(record, parent):
    authors = sorted(
        set(record["source_annotation_worker_ids"]) | set(parent["source_annotation_worker_ids"])
    )
    if record["fixed_boxes"] == parent["fixed_boxes"] and authors == sorted(
        record["source_annotation_worker_ids"]
    ):
        return record
    # A formerly fixed butterfly with bad bounds still needs a candidate.
    # Append it after the worker's boxes so an actual repair is evaluated first.
    candidates = list(record["candidate_boxes"])
    for frame in record["fixed_boxes"]:
        verdict = parent["decisions"].get(frame["box_id"], {})
        if verdict.get("answer") == "bad_geometry" or verdict.get("status") == "NEEDS_ANNOTATION":
            candidates.append(frame)
    return {
        **record,
        "fixed_boxes": parent["fixed_boxes"],
        "candidate_boxes": candidates,
        "source_annotation_worker_ids": authors,
    }


def select_scene(api, base, original, record, received, queue, minimum):
    """Return the suite for this exact scene. None suspends issuance until its parent settles."""
    row = api.db.execute(
        "SELECT key FROM objects WHERE id=? AND key LIKE 'suite:review:%'", (base,)
    ).fetchone()
    if not row:
        return base  # Older imported review records can lack a managed task suite.
    original_key = row[0]
    active = api.db.execute("SELECT active_key FROM review_scenes WHERE base=?", (base,)).fetchone()
    old_key = active[0] if active else original_key
    key = original_key
    if record is None:
        key = None
    elif record is not original:
        key += ":context:" + fingerprint(
            [record["fixed_boxes"], record["candidate_boxes"], record["source_annotation_worker_ids"]]
        )
    if old_key == key:
        return api.get(key)["id"] if key else None
    if old_key:
        page = api.get(old_key)
        if page["overlap"] > received[page["id"]]:
            api.patch_suite_overlap(old_key, 0)
    suite = None
    if key:
        if (
            key == original_key
            or api.db.execute('SELECT 1 FROM objects WHERE key=? AND status="DONE"', (key,)).fetchone()
        ):
            suite = api.get(key)
            if suite["overlap"] < minimum:
                api.patch_suite_overlap(key, minimum)
        else:
            q = queue()
            suite = q.create_review(key, review_suite(q.pool, record, minimum))
    with api.db:
        api.db.execute("INSERT OR REPLACE INTO review_scenes VALUES (?,?)", (base, key))
    event("validation.scene_changed", original_suite=base, active_suite=suite["id"] if suite else None)
    return suite["id"] if suite else None


def admitted_annotators(api, config):
    """The worker owns annotation exam grades and the production quality filter."""
    rows = []
    if api.db.execute("SELECT 1 FROM sqlite_master WHERE name='applied_skills'").fetchone():
        rows = api.db.execute("""SELECT exam.user_id, exam.value, quality.value
            FROM applied_skills exam LEFT JOIN applied_skills quality ON quality.user_id=exam.user_id
            AND quality.skill_id=(SELECT id FROM objects WHERE key='skill:annotation_work_quality')
            WHERE exam.skill_id=(SELECT id FROM objects WHERE key='skill:annotation_quality')""").fetchall()
    if not rows and not api.apply:
        return None  # Dry runs can supply synthetic workers without simulating their exams.
    return {
        worker
        for worker, exam, work in rows
        if exam >= config["annotation_threshold"]
        and (work is None or work >= config["work_quality"]["ban_below"])
    }
