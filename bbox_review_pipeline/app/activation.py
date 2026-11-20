"""Open only pools with new work, resuming moderation and asynchronous operations."""

import logging

from .api import APIError
from .worker_log import event


def open_resource(api, kind, identity, sent, operation):
    if not api.apply:
        return True
    endpoint = f"{kind}/{identity}"
    if operation:
        result = api.request("GET", "operations/" + operation)
        if result["status"] in ("PENDING", "RUNNING"):
            return False
        with api.db:
            api.db.execute("UPDATE launch_queue SET operation=NULL WHERE resource_id=?", (identity,))
        if result["status"] != "SUCCESS":
            raise APIError(f"Не удалось открыть {endpoint}: {result.get('details', result['status'])}")
    resource = api.request("GET", endpoint)
    if resource["status"] == "OPEN":
        return True
    if resource["status"] == "ARCHIVED":
        raise APIError("Пул в архиве: " + endpoint)
    if kind == "pools":
        checks = api.request("GET", f"/api/new/requester/pools/{identity}/validate")
        blockers = {check["type"] for check in checks if check.get("active") and check.get("blocker")}
        if "MUST_PASS_MODERATION" in blockers and not sent:
            api.request("PUT", f"/api/new/requester/poolModeration/{identity}", {"status": "READY"})
            with api.db:
                api.db.execute("UPDATE launch_queue SET moderation_sent=1 WHERE resource_id=?", (identity,))
            event("pool.moderation_submitted", pool=identity)
        if blockers:
            event("pool.waiting", pool=identity, reasons=sorted(blockers))
            return False
    result = api.request("POST", endpoint + "/open")
    if result and result.get("status") != "SUCCESS":
        if result["status"] == "FAIL":
            raise APIError(f"Операция открытия завершилась ошибкой: {endpoint}")
        with api.db:
            api.db.execute(
                "UPDATE launch_queue SET operation=? WHERE resource_id=?", (result["id"], identity)
            )
        return False
    return True


def open_ready_pools(api):
    rows = api.db.execute("""SELECT o.kind,o.key,q.resource_id,q.moderation_sent,q.operation
        FROM launch_queue q JOIN objects o ON o.id=q.resource_id AND o.kind IN ('trainings','pools')
        WHERE json_extract(o.payload,'$.project_id') IN
              (SELECT id FROM objects WHERE key IN ('project:bbox','project:validation'))
        ORDER BY o.kind='pools', o.rowid""").fetchall()
    for kind, key, identity, sent, operation in rows:
        try:
            if open_resource(api, kind, identity, sent, operation):
                with api.db:
                    api.db.execute("DELETE FROM launch_queue WHERE resource_id=?", (identity,))
                event("pool.open", resource=key, pool_id=identity)
        except APIError as error:
            # A training awaiting moderation must not hold up unrelated projects.
            event(
                "pool.open_failed",
                level=logging.WARNING,
                resource=key,
                error=str(error).splitlines()[0][:300],
            )
