"""Grade production annotators from independently reviewed work and restrict repeated low quality."""

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .worker_log import event


def utc(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def apply_work_quality(api, scores, policy, now=None):
    now = now or datetime.now(timezone.utc)
    # The qualification and work-quality skills belong to the requester and survive pool replacement.
    cached = set()
    if api.db.execute("SELECT 1 FROM sqlite_master WHERE name='applied_skills'").fetchone():
        cached = {
            w
            for (w,) in api.db.execute("""SELECT user_id FROM applied_skills WHERE skill_id=
            (SELECT id FROM objects WHERE key='skill:annotation_work_quality')""")
        }
    by_worker = defaultdict(list)
    for assignment_id, raw in api.db.execute(
        "SELECT id,data FROM assignments WHERE pool_key='bbox_production'"
    ):
        if assignment_id in scores:
            a = json.loads(raw)
            if a.get("status") in ("SUBMITTED", "ACCEPTED") and a.get("submitted"):
                photo = a["tasks"][0]["input_values"]["image_id"]
                by_worker[a["user_id"]].append(
                    (utc(a["submitted"]), assignment_id, photo, scores[assignment_id])
                )

    api.db.execute(
        "CREATE TABLE IF NOT EXISTS work_holds (worker TEXT, expires TEXT, PRIMARY KEY(worker, expires))"
    )
    for worker in sorted(cached | by_worker.keys()):
        deadlines = sorted(
            utc(e) for (e,) in api.db.execute("SELECT expires FROM work_holds WHERE worker=?", (worker,))
        )
        cutoff = max((d for d in deadlines if d <= now), default=None)
        active = bool(deadlines and deadlines[-1] > now)
        latest = {}
        for submitted, _, photo, score in sorted(by_worker[worker], reverse=True):
            if cutoff and submitted < cutoff:
                break
            latest.setdefault(photo, score)
            if len(latest) == policy["window"]:
                break
        if len(latest) < policy["minimum_photos"]:
            if worker in cached:
                api.clear_skill("annotation_work_quality", worker)
            poor = False
        else:
            grade = sum(latest.values()) / len(latest)
            poor = grade < policy["ban_below"]
            if poor and not active:
                durations = policy["ban_hours"]
                hours = durations[min(len(deadlines), len(durations) - 1)]
                deadline = (now + timedelta(hours=hours)).isoformat()
                with api.db:
                    api.db.execute("INSERT INTO work_holds VALUES (?,?)", (worker, deadline))
                event("annotation.work_restricted", worker=worker, grade=grade, expires=deadline)
            api.assign_skill("annotation_work_quality", worker, grade)
        # Revised independent votes can clear a restriction before its deadline.
        if active and not poor:
            with api.db:
                api.db.execute(
                    "DELETE FROM work_holds WHERE worker=? AND julianday(expires)>julianday(?)",
                    (worker, now.isoformat()),
                )


def release_expired_work_skills(api, threshold, now=None):
    """Check on idle polls too, so a worker can return without a new submission."""
    if not api.db.execute("SELECT 1 FROM sqlite_master WHERE name='work_holds'").fetchone():
        return
    if not api.db.execute("SELECT 1 FROM sqlite_master WHERE name='applied_skills'").fetchone():
        return
    now = (now or datetime.now(timezone.utc)).isoformat()
    rows = api.db.execute(
        """SELECT h.worker FROM work_holds h JOIN applied_skills s ON h.worker=s.user_id
        WHERE s.skill_id=(SELECT id FROM objects WHERE key='skill:annotation_work_quality')
        AND s.value < ? GROUP BY h.worker HAVING max(julianday(h.expires))<=julianday(?)""",
        (threshold, now),
    ).fetchall()
    for (worker,) in rows:
        api.clear_skill("annotation_work_quality", worker)
    return bool(rows)
