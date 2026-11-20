"""Run the public start command twice through a fake Yandex HTTP transport."""

import io
import json
import os
import signal
import sys
import unittest
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch
from urllib.parse import urlsplit

import run


class Response(io.BytesIO):
    status = 200


class Platform:
    def __init__(self):
        self.objects = {}
        self.created = Counter()

    def respond(self, request, timeout):
        method = request.method
        endpoint = urlsplit(request.full_url).path
        parts = endpoint.removeprefix("/api/v1/").split("/")
        if method == "POST" and len(parts) == 1:
            body = json.loads(request.data)
            identity = str(len(self.objects) + 1)
            for field in ("project_id", "pool_id"):
                if field in body:
                    assert body[field] in self.objects
            assert "__TASK_SCRIPT__" not in str(body)
            assert "@settings:" not in str(body)
            self.created[parts[0]] += 1
            result = {"id": identity, **body}
            if parts[0] in ("trainings", "pools"):
                result["status"] = "CLOSED"
            self.objects[identity] = result
        elif endpoint.endswith("/validate") and method == "GET":
            result = [{"type": "MUST_PASS_MODERATION", "active": False, "blocker": True}]
        elif method == "GET" and parts == ["assignments"]:
            result = {"items": [], "has_more": False}
        elif method == "GET" and len(parts) == 2:
            result = self.objects[parts[1]]
        elif method == "POST" and parts[-1] == "open":
            self.objects[parts[1]]["status"] = "OPEN"
            result = {"id": "opened", "status": "SUCCESS"}
        else:
            raise AssertionError((method, endpoint))
        return Response(json.dumps(result).encode())


class SingleCycle(Event):
    def wait(self, timeout=None):
        self.set()
        return True


class StartTest(unittest.TestCase):
    def test_clean_installation_and_repeated_start(self):
        platform = Platform()
        umask = os.umask(0o077)
        self.addCleanup(os.umask, umask)
        with TemporaryDirectory() as scratch:
            root = Path(scratch)
            with (
                patch("app.api.ROOT", root),
                patch.object(run, "ROOT", root),
                patch.dict(os.environ, OAUTH_TOKEN="offline-test"),
                patch("urllib.request.urlopen", side_effect=platform.respond),
                patch("app.worker.threading.Event", SingleCycle),
                patch.object(signal, "signal"),
                patch.object(sys, "argv", ["run.py", "start"]),
                redirect_stdout(io.StringIO()),
            ):
                run.main()
                self.assertEqual(
                    {
                        key: platform.created[key]
                        for key in ("projects", "trainings", "pools", "skills", "tasks")
                    },
                    {"projects": 2, "trainings": 2, "pools": 5, "skills": 3, "tasks": 15},
                )
                pools = {
                    obj["private_name"]: obj["id"]
                    for obj in platform.objects.values()
                    if "reward_per_assignment" in obj
                }
                self.assertEqual(
                    set(pools),
                    {
                        "bbox_qualification",
                        "bbox_production",
                        "validation_exam",
                        "validation_annotation_exam",
                        "validation_production",
                    },
                )
                work_pages = [
                    obj
                    for obj in platform.objects.values()
                    if obj.get("pool_id") == pools["validation_production"]
                    and not obj["tasks"][0].get("known_solutions")
                ]
                self.assertEqual(len(work_pages), 205)
                report = json.loads((root / "state/status.json").read_text())
                self.assertNotIn("error", report)
                self.assertEqual(report["selected_photos"], 205)
                self.assertEqual(report["photos"], {"WAITING_VALIDATION": 205})
                opened = sum(obj.get("status") == "OPEN" for obj in platform.objects.values())
                self.assertEqual(opened, 5)  # Both trainings, both exams and the model review pool.
                total = len(platform.objects)
                run.main()
                self.assertEqual(len(platform.objects), total)
