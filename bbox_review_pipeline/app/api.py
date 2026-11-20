"""Standard-library API client. Tokens never enter logs. Projects and tasks are journaled locally."""

import fcntl
import hashlib
import json
import logging
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from .worker_log import event

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://tasks.yandex.ru/api/v1/"


def dump(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)


def save_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(dump(value))
    temporary.replace(path)


class APIError(RuntimeError):
    pass


class PipelineBusy(RuntimeError):
    pass


@contextmanager
def pipeline_lock(directory):
    """Serialize edits to the journal across the worker and requester commands."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "pipeline.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PipelineBusy(
                "Другой процесс работает с конвейером. Повторите команду после завершения цикла."
            ) from None
        yield


class API:
    def __init__(self, apply=False, state_dir=None):
        self.apply = apply
        self.state = Path(state_dir or ROOT / "state")
        self.review_state = self.state / "dry_run" if not apply and state_dir is None else self.state
        self.review_state.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.state / ("pipeline.sqlite3" if apply else "dry_run.sqlite3"))
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS objects (key TEXT PRIMARY KEY, kind TEXT, id TEXT, payload TEXT, response TEXT, status TEXT)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS assignments (id TEXT PRIMARY KEY, pool_key TEXT, data TEXT)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS launch_queue (resource_id TEXT PRIMARY KEY, moderation_sent INTEGER DEFAULT 0, operation TEXT)"
        )
        self.token = os.getenv("OAUTH_TOKEN")
        if apply and not self.token:
            raise APIError("OAUTH_TOKEN is missing")

    def request(self, method, endpoint, payload=None):
        if not self.apply:
            return {
                "id": "dry-" + hashlib.sha256((endpoint + dump(payload)).encode()).hexdigest()[:10],
                **(payload or {}),
            }
        data = None if payload is None else dump(payload).encode()
        req = urllib.request.Request(
            (
                "https://tasks.yandex.ru" + endpoint
                if endpoint.startswith("/api/new/requester/")
                else BASE + endpoint
            ),
            data=data,
            method=method,
            headers={"Authorization": "OAuth " + self.token, "Content-Type": "application/json"},
        )
        for attempt in range(4):
            # Only the resource and assignment/page identifiers belong in logs.
            resource = endpoint.partition("?")[0]
            started = time.monotonic()
            event("api.request", method=method, resource=resource, attempt=attempt + 1)
            try:
                with urllib.request.urlopen(req, timeout=40) as r:
                    response = None if r.status == 204 else json.loads(r.read() or b"null")
                    event(
                        "api.response",
                        method=method,
                        resource=resource,
                        status=r.status,
                        duration_ms=round(1000 * (time.monotonic() - started)),
                    )
                    return response
            except urllib.error.HTTPError as e:
                body = e.read().decode()
                event(
                    "api.http_error", level=logging.WARNING, method=method, resource=resource, status=e.code
                )
                if (e.code == 429 or (method == "GET" and e.code >= 500)) and attempt < 3:
                    event("api.retry", method=method, resource=resource, delay_seconds=2**attempt)
                    time.sleep(2**attempt)
                    continue
                raise APIError(f"{method} {endpoint}: HTTP {e.code}: {body}") from None
            except (urllib.error.URLError, TimeoutError) as e:
                event(
                    "api.network_error",
                    level=logging.WARNING,
                    method=method,
                    resource=resource,
                    kind=type(e).__name__,
                )
                if method == "GET" and attempt < 3:
                    event("api.retry", method=method, resource=resource, delay_seconds=2**attempt)
                    time.sleep(2**attempt)
                    continue
                raise APIError(
                    f"{method} {endpoint}: outcome unknown; reconcile before retrying ({type(e).__name__})"
                ) from None

    def list(self, kind, **filters):
        if not self.apply:
            return []
        result = []
        while True:
            page = self.request(
                "GET", kind + "?" + urllib.parse.urlencode({"limit": 100, "sort": "id", **filters})
            )
            result.extend(page["items"])
            if not page.get("has_more"):
                return result
            filters["id_gt"] = page["items"][-1]["id"]

    def create(self, key, kind, payload):
        row = self.db.execute("SELECT id,response,status,payload FROM objects WHERE key=?", (key,)).fetchone()
        if row:
            if row[2] == "DONE":
                return json.loads(row[1])
            event("object.pending", level=logging.ERROR, key=key, kind=kind)
            raise APIError(
                f"Unresolved POST for {key}. Inspect remote objects and local journal before retrying; no duplicate POST sent."
            )
        self.db.execute(
            "INSERT INTO objects VALUES (?,?,?,?,?,?)", (key, kind, None, dump(payload), None, "PENDING")
        )
        self.db.commit()
        try:
            response = self.request(
                "POST",
                kind + ("?async_mode=false&open_pool=false" if kind in ("task-suites", "tasks") else ""),
                payload,
            )
        except APIError as e:
            # Definite validation rejection means no object was created. Unknown POST outcome remains pending.
            if any(f"HTTP {c}:" in str(e) for c in (400, 401, 403, 404, 409, 422, 429)):
                self.db.execute("DELETE FROM objects WHERE key=?", (key,))
                self.db.commit()
            raise
        if not self.apply:
            # Separate managed objects get separate IDs even with equal payloads,
            # just as they do on the server (important for version replacements).
            response["id"] = "dry-" + hashlib.sha256((key + dump(payload)).encode()).hexdigest()[:10]
            # A retired page and its replacement may have identical inputs and eligibility.
            while self.db.execute("SELECT 1 FROM objects WHERE id=?", (response["id"],)).fetchone():
                response["id"] = "dry-" + hashlib.sha256(response["id"].encode()).hexdigest()[:10]
        self.db.execute(
            "UPDATE objects SET id=?,response=?,status=? WHERE key=?",
            (response["id"], dump(response), "DONE", key),
        )
        if kind in ("tasks", "task-suites") and (payload.get("overlap") or payload.get("infinite_overlap")):
            self.queue_open(payload["pool_id"])
        self.db.commit()
        if self.apply:
            print(f"Создан {key} → {response['id']}", flush=True)
        event(
            "object.created",
            key=key,
            kind=kind,
            object_id=response["id"],
            pool_id=payload.get("pool_id"),
            task_count=len(payload.get("tasks", [])),
        )
        self.save_manifest()
        return response

    def patch_suite_overlap(self, key, overlap):
        obj = self.get(key)
        payload = {"overlap": overlap, "infinite_overlap": False}
        endpoint = (
            "task-suites/" + obj["id"] + ("/set-overlap-or-min" if overlap == 0 else "?open_pool=false")
        )
        response = self.request("PATCH", endpoint, payload) if self.apply else {**obj, **payload}
        if not self.apply and overlap == 0:
            # The live endpoint preserves already issued places.
            response["overlap"] = self.db.execute(
                """SELECT count(*) FROM assignments
                WHERE json_extract(data,'$.task_suite_id')=? AND
                coalesce(json_extract(data,'$.status'),'ACCEPTED') IN ('ACTIVE','SUBMITTED','ACCEPTED')""",
                (obj["id"],),
            ).fetchone()[0]
        row = self.db.execute("SELECT payload FROM objects WHERE key=?", (key,)).fetchone()
        original = {
            **json.loads(row[0]),
            "overlap": response["overlap"],
            "infinite_overlap": response["infinite_overlap"],
        }
        self.db.execute(
            "UPDATE objects SET payload=?,response=? WHERE key=?", (dump(original), dump(response), key)
        )
        if response["overlap"] > obj["overlap"]:
            self.queue_open(obj["pool_id"])
        self.db.commit()
        return response

    def queue_open(self, resource_id):
        self.db.execute("INSERT OR IGNORE INTO launch_queue(resource_id) VALUES (?)", (resource_id,))

    def get(self, key):
        row = self.db.execute('SELECT response FROM objects WHERE key=? AND status="DONE"', (key,)).fetchone()
        if not row:
            raise APIError("Run setup first: " + key)
        return json.loads(row[0])

    def save_manifest(self):
        objects = {
            k: {"type": t, "id": i}
            for k, t, i in self.db.execute('SELECT key,kind,id FROM objects WHERE status="DONE"')
        }
        target = self.state / ("manifest.json" if self.apply else "dry_run_manifest.json")
        save_json(target, objects)

    def record_assignment(self, pool_key, assignment):
        # Keep rowid stable: routing uses ingestion order to space control pages.
        changed = self.db.execute(
            """INSERT INTO assignments VALUES (?,?,?)
            ON CONFLICT(id) DO UPDATE SET pool_key=excluded.pool_key, data=excluded.data
            WHERE assignments.pool_key != excluded.pool_key OR assignments.data != excluded.data""",
            (assignment["id"], pool_key, dump(assignment)),
        ).rowcount
        self.db.commit()
        if changed:
            event(
                "assignment.saved",
                assignment_id=assignment["id"],
                pool=pool_key,
                status=assignment.get("status"),
                tasks=len(assignment.get("tasks", [])),
            )
        return changed

    def assign_skill(self, name, user_id, value):
        payload = {"skill_id": self.get("skill:" + name)["id"], "user_id": user_id, "value": round(value, 3)}
        self.db.execute("""CREATE TABLE IF NOT EXISTS applied_skills (
            skill_id TEXT, user_id TEXT, value REAL NOT NULL, PRIMARY KEY(skill_id, user_id))""")
        previous = self.db.execute(
            "SELECT value FROM applied_skills WHERE skill_id=? AND user_id=?", (payload["skill_id"], user_id)
        ).fetchone()
        if previous and previous[0] == payload["value"]:
            return
        result = self.request("PUT", "user-skills", payload)
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO applied_skills VALUES (?,?,?)",
                (payload["skill_id"], user_id, payload["value"]),
            )
        event("skill.updated", skill=name, skill_id=payload["skill_id"], value=payload["value"])
        with (self.state / "skill_updates.jsonl").open("a") as f:
            f.write(json.dumps({"applied": self.apply, **payload}) + "\n")
        return result

    def clear_skill(self, name, user_id):
        """Withdraw only a skill value previously managed by this processor."""
        skill_id = self.get("skill:" + name)["id"]
        row = self.db.execute(
            "SELECT 1 FROM applied_skills WHERE skill_id=? AND user_id=?", (skill_id, user_id)
        ).fetchone()
        if not row:
            return
        for value in self.list("user-skills", user_id=user_id, skill_id=skill_id):
            if value["user_id"] == user_id and value["skill_id"] == skill_id:
                self.request("DELETE", "user-skills/" + value["id"])
        with self.db:
            self.db.execute("DELETE FROM applied_skills WHERE skill_id=? AND user_id=?", (skill_id, user_id))
        event("skill.cleared", skill=name, worker=user_id)

    def accept_exam(self, assignment_id):
        """Reconcile an accepted annotation exam with the assignment journal."""
        row = self.db.execute("SELECT pool_key,data FROM assignments WHERE id=?", (assignment_id,)).fetchone()
        if not row or row[0] != "bbox_qualification":
            raise APIError("Acceptance is restricted to managed annotation exams")
        source = json.loads(row[1])
        current = self.request("GET", "assignments/" + assignment_id) if self.apply else source
        if (
            current.get("pool_id") != self.get("pool:bbox_qualification")["id"]
            or current.get("user_id") != source["user_id"]
        ):
            raise APIError("Exam assignment identity mismatch")
        if current["status"] == "SUBMITTED":
            current = (
                self.request("PATCH", "assignments/" + assignment_id, {"status": "ACCEPTED"})
                if self.apply
                else {**current, "status": "ACCEPTED"}
            )
        elif current["status"] != "ACCEPTED":
            raise APIError("Exam is not submitted or already accepted: " + current["status"])
        self.record_assignment("bbox_qualification", current)
        return current

    def settle_validator_exam(self, source, passed):
        current = self.request("GET", "assignments/" + source["id"]) if self.apply else source
        identity = (
            source["id"],
            source["user_id"],
            self.get("pool:validation_exam")["id"],
            source["task_suite_id"],
        )

        def check_identity(assignment):
            return tuple(assignment.get(k) for k in ("id", "user_id", "pool_id", "task_suite_id")) == identity

        if not check_identity(current):
            raise APIError("Validation exam assignment identity mismatch")
        target = "ACCEPTED" if passed else "REJECTED"
        if current["status"] == "SUBMITTED" or (passed and current["status"] == "REJECTED"):
            decision = {"status": target}
            if not passed:
                decision["public_comment"] = (
                    "Экзамен не пройден. Ответы по рамкам и пропускам не набрали проходной балл."
                )
            if self.apply:
                try:
                    current = self.request("PATCH", "assignments/" + source["id"], decision)
                except APIError:
                    # Native control rules may already have settled the same submission.
                    current = self.request("GET", "assignments/" + source["id"])
                    if current.get("status") not in (target, "ACCEPTED"):
                        raise
            else:
                current = {**current, **decision}
        if not check_identity(current) or current["status"] not in (target, "ACCEPTED"):
            raise APIError("Unconfirmed validation exam decision")
        self.record_assignment("validation_exam", current)
        return current
