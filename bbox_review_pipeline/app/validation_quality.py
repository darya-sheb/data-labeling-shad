"""Replay control results in submission order across both validation pools."""

import json
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from .api import save_json
from .work_quality import utc
from .worker_log import event


def control_points(tasks, assignment):
    outputs = {}
    for task, solution in zip(assignment.get("tasks", []), assignment.get("solutions") or []):
        item = task.get("input_values", {}).get("review_item_id")
        if item and isinstance(solution, dict) and isinstance(solution.get("output_values"), dict):
            outputs[item] = solution["output_values"]
    points = []
    hard_page = False
    for task in tasks:
        item = task["input_values"]
        if item.get("review_type") == "box" and any(
            b.get("fixed") and b["box_id"] == item.get("focus_box_id") for b in item.get("context_boxes", [])
        ):
            continue  # Legacy control suites also asked about the accepted reference itself.
        output = outputs.get(item["review_item_id"], {})
        accepted = [s["output_values"] for s in task["known_solutions"] if s["correctness_weight"] == 1]
        default = "missing_no" if item.get("review_type") == "coverage" else "box_correct"
        hard_page |= not any(gold.get("answer") == default for gold in accepted)
        correct = any(all(output.get(k) == v for k, v in gold.items()) for gold in accepted)
        points.append((correct, output.get("answer") == default))
    return points, hard_page


def control_action(window, config):
    """Evaluate only a full window of work controls at a page boundary."""
    if len(window) != config["validation_control_window"]:
        return None
    correct = sum(point for point, _ in window)
    rate = 100 * correct / len(window)
    if len(window) - correct >= config["validation_default_min_errors"] and all(
        default for _, default in window
    ):
        return "default_pattern"
    if rate < config["validation_discard_below"]:
        return "low_accuracy"
    if rate < config["validation_pause_below"]:
        return "pause"
    return None


def restrict_validator(api, worker, deadline):
    """A project restriction expires on the platform even if polling stops."""
    project = api.get("project:validation")["id"]
    expires = deadline.isoformat()
    api.db.execute(
        "CREATE TABLE IF NOT EXISTS validator_restrictions (project TEXT, worker TEXT, expires TEXT, PRIMARY KEY(project,worker))"
    )
    row = api.db.execute(
        "SELECT expires FROM validator_restrictions WHERE project=? AND worker=?", (project, worker)
    ).fetchone()
    if row and utc(row[0]) >= deadline:
        return
    restrictions = api.list("user-restrictions", user_id=worker)
    covered = any(
        b.get("scope") == "PROJECT"
        and b.get("project_id") == project
        and (not b.get("will_expire") or utc(b["will_expire"]) >= deadline)
        for b in restrictions
    )
    if not covered:
        api.request(
            "PUT",
            "user-restrictions",
            {
                "scope": "PROJECT",
                "project_id": project,
                "user_id": worker,
                "will_expire": deadline.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            },
        )
    with api.db:
        api.db.execute(
            "INSERT OR REPLACE INTO validator_restrictions VALUES (?,?,?)", (project, worker, expires)
        )
    event("validator.restricted", worker=worker, project_id=project, expires=expires)


def validation_submissions(api):
    """Yield submitted assignments with trusted control keys, including older pool generations."""
    keys = ("validation_exam", "validation_production", "validation_annotation_exam")
    assignments = [
        (pool, json.loads(raw))
        for pool, raw in api.db.execute(
            "SELECT pool_key,data FROM assignments WHERE pool_key IN (?,?,?) ORDER BY id", keys
        )
    ]
    assignments = [
        (pool, a) for pool, a in assignments if a.get("status", "ACCEPTED") in ("SUBMITTED", "ACCEPTED")
    ]
    suite_ids = {a.get("task_suite_id") for _, a in assignments}
    gold = {}
    for suite_id, raw in api.db.execute("""SELECT id,payload FROM objects WHERE kind='task-suites'
            AND status='DONE' AND json_type(payload,'$.tasks[0].known_solutions')='array'"""):
        if suite_id in suite_ids:
            gold[suite_id] = json.loads(raw)["tasks"]
    for pool, a in assignments:
        tasks = a.get("tasks") or []
        source = gold.get(a.get("task_suite_id"))
        if source is None and tasks and all(t.get("known_solutions") for t in tasks):
            source = tasks
        yield pool, a, source


def correction_rejections(submissions):
    """Keep the first rejection per photo, revision and worker, even if a ballot is later quarantined."""
    history = defaultdict(dict)
    for pool, assignment, control in submissions:
        if control or pool == "validation_exam":
            continue
        worker = assignment.get("user_id")
        if not worker:
            continue
        for task, solution in zip(assignment.get("tasks") or [], assignment.get("solutions") or []):
            v = task.get("input_values", {})
            if not isinstance(solution, dict) or not isinstance(solution.get("output_values"), dict):
                continue
            answer = solution["output_values"].get("answer")
            if v.get("review_type") == "coverage":
                rejected = answer == "missing_yes"
            elif v.get("review_type") == "box":
                rejected = answer in ("bad_geometry", "extra_box")
                if answer == "duplicate":
                    rejected = not any(
                        b.get("fixed") and b["box_id"] == v.get("focus_box_id")
                        for b in v.get("context_boxes", [])
                    )
            else:
                continue
            if rejected and v.get("image_url") and type(v.get("revision")) is int:
                revisions = history[v["image_url"]].setdefault(worker, {})
                when = utc(assignment["submitted"]) if assignment.get("submitted") else None
                rev = v["revision"]
                if (
                    rev not in revisions
                    or when is None
                    or (revisions[rev] is not None and when < revisions[rev])
                ):
                    revisions[rev] = when
    return history


def blocking_reviewers(history, photo, correction_revision, submitted=None):
    return {
        worker
        for worker, revisions in history.get(photo, {}).items()
        if any(
            rev < correction_revision and (submitted is None or when is None or when <= submitted)
            for rev, when in revisions.items()
        )
    }


def validation_ballots(api, config, report, now=None, *, submissions=None):
    now = now or datetime.now(timezone.utc)
    controls = defaultdict(list)
    ordinary = []
    if submissions is None:
        submissions = validation_submissions(api)
    for pool, a, source in submissions:
        if pool == "validation_exam":
            continue  # Exam admission and payment are evaluated from its own issued page.
        if source:
            photo = source[0]["input_values"].get("image_id")
            controls[a["user_id"]].append(
                (utc(a["submitted"]), a["id"], pool, photo, *control_points(source, a))
            )
        else:
            ordinary.append(a)

    quarantines = defaultdict(list)
    audit = {}
    for worker, timeline in controls.items():
        window = deque(maxlen=config["validation_control_window"])
        default_photos = {}
        checkpoint = until = None
        for submitted, identity, pool, photo, points, hard_page in sorted(timeline):
            if until and submitted < until:
                continue
            window.extend(points)
            if hard_page:
                if all(default for _, default in points):
                    if photo:
                        default_photos.setdefault(photo, identity)
                else:
                    default_photos.clear()
            early_pattern = len(default_photos) >= config["validation_default_streak_photos"]
            action = "default_pattern_streak" if early_pattern else control_action(window, config)
            if action:
                strikes = audit.setdefault(worker, [])
                durations = config["validation_cooldown_hours"]
                hours = durations[min(len(strikes), len(durations) - 1)]
                until = submitted + timedelta(hours=hours)
                if action != "pause":
                    quarantines[worker].append((checkpoint, until, len(strikes)))
                strikes.append(
                    {
                        "failed_control": identity,
                        "action": action,
                        "duration_hours": hours,
                        "correct": sum(correct for correct, _ in window),
                        "questions": len(window),
                        "after": checkpoint.isoformat() if checkpoint else None,
                        "until": until.isoformat(),
                        "excluded_assignments": [],
                    }
                )
                if early_pattern:
                    strikes[-1]["pattern_controls_by_photo"] = dict(default_photos)
                default_photos.clear()
                window.clear()
                checkpoint = until
            elif hard_page and all(correct for correct, _ in points):
                checkpoint = submitted
        if until and until > now:
            restrict_validator(api, worker, until)

    votes = defaultdict(lambda: defaultdict(list))
    received = defaultdict(int)
    excluded_suites = set()
    for a in sorted(ordinary, key=lambda a: (a.get("submitted") or "", a["id"])):
        suite = a.get("task_suite_id")
        received[suite] += 1  # Consumed overlap includes invalid, excluded and incomplete submissions.
        worker = a["user_id"]
        submitted = utc(a["submitted"]) if a.get("submitted") else None
        period = next(
            (
                i
                for after, until, i in quarantines.get(worker, [])
                if submitted is None or ((after is None or submitted > after) and submitted < until)
            ),
            None,
        )
        if period is not None:
            audit[worker][period]["excluded_assignments"].append(a["id"])
            excluded_suites.add(suite)
            continue
        for task, solution in zip(a.get("tasks") or [], a.get("solutions") or []):
            item = task.get("input_values", {}).get("review_item_id")
            answer = ((solution or {}).get("output_values") or {}).get("answer")
            if item and isinstance(answer, str):
                votes[suite][item].append((worker, answer))
    save_json(report, audit)
    return votes, received, excluded_suites


def validator_exams(api, config):
    """Use the exact ten trusted questions issued, including the two permitted duplicate reasons."""
    report = []
    for (raw,) in api.db.execute(
        "SELECT data FROM assignments WHERE pool_key='validation_exam' ORDER BY rowid"
    ).fetchall():
        a = json.loads(raw)
        if a.get("status") not in ("SUBMITTED", "ACCEPTED", "REJECTED"):
            continue
        row = api.db.execute(
            """SELECT payload FROM objects WHERE id=? AND kind='task-suites'
            AND (key='suite:validation_exam:1' OR key LIKE 'history:%:suite:validation_exam:1')""",
            (a.get("task_suite_id"),),
        ).fetchone()
        grade = None
        if row:
            page = json.loads(row[0])
            tasks = page["tasks"]
            expected = [t["input_values"]["review_item_id"] for t in tasks]
            actual = [t.get("input_values", {}).get("review_item_id") for t in a.get("tasks", [])]
            if (
                page["pool_id"] == a.get("pool_id")
                and len(set(expected)) == len(tasks) == config["validation_exam_questions"]
                and sorted(x for x in actual if isinstance(x, str)) == sorted(expected)
                and len(actual) == len(expected)
                and len(a.get("solutions") or []) == len(tasks)
                and all(
                    isinstance(s, dict)
                    and isinstance(s.get("output_values"), dict)
                    and s["output_values"].get("answer")
                    in ("box_correct", "extra_box", "bad_geometry", "duplicate", "missing_yes", "missing_no")
                    for s in a["solutions"]
                )
            ):
                points, _ = control_points(tasks, a)
                if len(points) == len(tasks):
                    grade = 100 * sum(correct for correct, _ in points) / len(tasks)
        status = a["status"]
        if grade is not None:
            api.assign_skill("validation_quality", a["user_id"], grade)
            passed = grade >= config["validation_threshold"]
            target = "ACCEPTED" if passed else "REJECTED"
            if status != target and status != "ACCEPTED":
                status = api.settle_validator_exam(a, passed)["status"]
        report.append(
            {
                "assignment_id": a["id"],
                "score": grade,
                "review_complete": grade is not None,
                "passed": grade >= config["validation_threshold"] if grade is not None else None,
                "payment_status": status,
            }
        )
    return report
