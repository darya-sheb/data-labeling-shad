"""Exercise production entry points with an isolated journal and synthetic submissions."""

import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.activation import open_ready_pools
from app.api import API
from app.deployment import setup
from app.materials import CONFIG, load
from app.models import accepted_frames, aggregate, annotation, candidates
from app.review import accept_photo, process
from app.worker import cycle


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        quiet = redirect_stdout(StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)
        self.api = API(False, state_dir=self.tmp.name)
        self.addCleanup(self.api.db.close)
        self.state = Path(self.tmp.name)
        self.seq = 0

    def submit(self, pool, page, worker, outputs, status="ACCEPTED"):
        self.seq += 1
        identity = f"a{self.seq:05d}"
        self.assertEqual(len(outputs), len(page["tasks"]))
        a = {
            "id": identity,
            "user_id": worker,
            "task_suite_id": page["id"],
            "pool_id": page["pool_id"],
            "tasks": [{"input_values": t["input_values"]} for t in page["tasks"]],
            "solutions": [{"output_values": o} for o in outputs],
            "status": status,
            "submitted": "2026-01-01T12:00:00",
        }
        self.api.record_assignment(pool, a)
        return identity

    def ballot(self, key, worker, first="box_correct"):
        page = self.api.get(key)
        self.assertNotIn(worker, page["unavailable_for"])
        return self.submit(
            "validation_production",
            page,
            worker,
            [
                {"answer": first if t["input_values"]["review_type"] == "box" else "missing_no"}
                for t in page["tasks"]
            ],
        )

    def test_published_votes_reproduce_reference_byte_for_byte(self):
        from app.api import ROOT
        from app.replay import replay

        out = self.state / "golden.jsonl"
        self.assertEqual(replay(out), 400)
        self.assertEqual(out.read_bytes(), (ROOT / "reference/golden.jsonl").read_bytes())

    def test_from_supplied_photos_to_correction_and_full_export(self):
        setup(self.api)
        photos = load("photos")
        ids = json.loads((self.state / "selection.json").read_text())
        model_ids = {p["image_id"] for p in photos if p["boxes"]}
        crowd_ids = {p["image_id"] for p in photos if p["filter_yes"] >= 2}
        self.assertEqual(len(photos), 400)
        self.assertEqual(len(ids), 205)
        self.assertEqual(set(ids), model_ids | crowd_ids)
        self.assertTrue(model_ids - crowd_ids)
        self.assertTrue(crowd_ids - model_ids)
        for image in crowd_ids - model_ids:
            page = self.api.get("suite:review:model:" + image)
            self.assertEqual([t["input_values"]["review_type"] for t in page["tasks"]], ["coverage"])
        before = self.api.db.execute("SELECT count(*) FROM objects").fetchone()
        setup(self.api)
        self.assertEqual(before, self.api.db.execute("SELECT count(*) FROM objects").fetchone())
        gap = 0
        for (raw,) in self.api.db.execute(
            "SELECT payload FROM objects WHERE kind='task-suites' AND json_extract(payload,'$.pool_id')=? ORDER BY rowid",
            (self.api.get("pool:validation_production")["id"],),
        ):
            tasks = json.loads(raw)["tasks"]
            if tasks[0].get("known_solutions"):
                self.assertIn(gap, range(8, 13))
                self.assertEqual(tasks[-1]["input_values"]["review_type"], "coverage")
                gap = 0
            else:
                gap += 1
        chosen = next(p for p in photos if len(p["boxes"]) == 1)
        identity = chosen["image_id"]
        for photo in ids:
            key = "suite:review:model:" + photo
            self.ballot(key, "v1")
            self.ballot(key, "v2", "bad_geometry" if photo == identity else "box_correct")
        cycle(self.api)
        key = "suite:review:model:" + identity
        self.assertEqual(self.api.get(key)["overlap"], 3)
        self.assertFalse((self.state / "golden.jsonl").exists())
        self.ballot(key, "v3", "bad_geometry")
        cycle(self.api)
        fix = self.api.get("suite:reannotation:" + identity + ":2")
        self.assertEqual(set(fix["unavailable_for"]), {"v2", "v3"})
        bounds = [0.2, 0.15, 0.7, 0.85]
        aid = self.submit(
            "bbox_production", fix, "annotator", [{"result": [annotation(bounds)], "reviewed": True}]
        )
        cycle(self.api)
        key = "suite:review:" + aid
        self.assertIn("annotator", self.api.get(key)["unavailable_for"])
        self.ballot(key, "v1")
        self.ballot(key, "v4")
        # A fresh client resumes the previous journal.
        resumed = API(False, state_dir=self.tmp.name)
        try:
            self.assertTrue(cycle(resumed)["exported"])
        finally:
            resumed.db.close()
        lines = [json.loads(line) for line in (self.state / "golden.jsonl").read_text().splitlines()]
        self.assertEqual([r["photo_id"] for r in lines], [int(p["image_id"]) for p in photos])
        by_id = {str(r["photo_id"]): r["boxes"] for r in lines}
        self.assertEqual(by_id[identity], [{"left": 0.2, "top": 0.15, "width": 0.5, "height": 0.7}])
        self.assertTrue(all(by_id[p["image_id"]] == [] for p in photos if p["image_id"] not in ids))

    def test_exams_are_paid_and_routed_independently(self):
        setup(self.api)
        for key, capacity in [("suite:validation_exam:1", 10), ("suite:bbox_qualification:exam10", 7)]:
            page = self.api.get(key)
            self.assertEqual((len(page["tasks"]), page["overlap"]), (10, capacity))
        exam = self.api.get("suite:validation_exam:1")
        right = [t["known_solutions"][0]["output_values"] for t in exam["tasks"]]
        self.submit("validation_exam", exam, "vpass", right, "SUBMITTED")
        wrong = [{"answer": "bad_geometry" if o["answer"] != "bad_geometry" else "extra_box"} for o in right]
        self.submit("validation_exam", exam, "vfail", wrong, "SUBMITTED")
        bbox = self.api.get("suite:bbox_qualification:exam10")
        workbook = load("bbox_exam")
        correct = [
            {
                "result": [annotation(b) for b in p["reference_boxes"]],
                "reviewed": True,
                "empty_confirmed": not p["reference_boxes"],
            }
            for p in workbook
        ]
        auto = self.submit("bbox_qualification", bbox, "apass", correct, "SUBMITTED")
        p = workbook[0]["reference_boxes"][0]
        cropped = [p[0], p[1], p[0] + 0.7 * (p[2] - p[0]), p[3]]
        trial = self.submit(
            "bbox_qualification",
            bbox,
            "borderline",
            [{"result": [annotation(cropped)], "reviewed": True}, *correct[1:]],
            "SUBMITTED",
        )
        cycle(self.api)
        v = json.loads((self.state / "validation_exam_acceptance.json").read_text())
        self.assertEqual({r["score"]: r["payment_status"] for r in v}, {100: "ACCEPTED", 0: "REJECTED"})
        self.assertEqual(
            len(
                list(
                    self.api.db.execute(
                        "SELECT 1 FROM objects WHERE key LIKE ?", ("suite:review:" + trial + "_%",)
                    )
                )
            ),
            1,
        )
        self.assertIsNone(
            self.api.db.execute(
                "SELECT 1 FROM objects WHERE key LIKE ?", ("suite:review:" + auto + "_%",)
            ).fetchone()
        )
        review = self.api.get("suite:review:" + trial + "_0")
        self.assertEqual(review["pool_id"], self.api.get("pool:validation_annotation_exam")["id"])
        self.assertIn("borderline", review["unavailable_for"])
        for voter in ("v1", "v2"):
            self.submit(
                "validation_annotation_exam",
                review,
                voter,
                [
                    {"answer": "bad_geometry" if t["input_values"]["review_type"] == "box" else "missing_no"}
                    for t in review["tasks"]
                ],
            )
        cycle(self.api)
        grades = {
            r["assignment_id"]: r for r in json.loads((self.state / "exam_acceptance.json").read_text())
        }
        self.assertEqual(grades[trial]["payment_status"], "ACCEPTED")
        self.assertTrue(grades[trial]["passed"])
        self.assertEqual(grades[auto]["score"], 100)

    def test_acceptance_keeps_coordinates_and_requires_two_rejected_versions(self):
        setup(self.api)
        identity = next(p["image_id"] for p in load("photos") if len(p["boxes"]) == 1)
        key = "suite:review:model:" + identity

        def reject(key):
            for voter in ("v1", "v2"):
                self.ballot(key, voter, "bad_geometry")

        reject(key)
        queue = self.state / "acceptance_queue.json"
        with patch.dict(CONFIG, max_reannotations_per_image=0):
            process(self.api)
            self.assertEqual(json.loads(queue.read_text()), [])
            with self.assertRaises(ValueError):
                accept_photo(self.api, identity)
        process(self.api)
        fix = self.api.get(f"suite:reannotation:{identity}:2")
        bounds = [0.1, 0.2, 0.5, 0.6]
        aid = self.submit(
            "bbox_production", fix, "artist", [{"result": [annotation(bounds)], "reviewed": True}]
        )
        cycle(self.api)
        reject("suite:review:" + aid)
        process(self.api)
        (row,) = json.loads(queue.read_text())
        self.assertEqual(row["rejected_revisions"], [1, 2])
        self.assertEqual(row["boxes"], [bounds])
        with patch.object(self.api, "list", return_value=[{"task_suite_id": row["next_correction_suite"]}]):
            with self.assertRaises(ValueError):
                accept_photo(self.api, row["acceptance_id"])
        accept_photo(self.api, row["acceptance_id"])
        self.assertEqual(self.api.get(f"suite:reannotation:{identity}:3")["overlap"], 0)
        process(self.api)
        accept_photo(self.api, row["acceptance_id"])
        self.assertEqual(json.loads(queue.read_text()), [])
        result = next(
            r for r in json.loads((self.state / "results.json").read_text()) if r["image_id"] == identity
        )
        self.assertEqual(result["status"], "FINAL")
        self.assertEqual(result["fixed_boxes"][0]["bbox"], bounds)
        verdict = result["decisions"][identity + "_r2_b0"]
        self.assertEqual((verdict["answer"], verdict["vote_count"]), ("bad_geometry", 2))

    def test_acceptance_cannot_add_removed_boxes_or_confirm_an_empty_scene(self):
        bounds = [0.2, 0.2, 0.7, 0.7]
        frames = candidates("photo", 2, [bounds, bounds, bounds])
        record = {"image_id": "photo", "revision": 2, "candidate_boxes": frames}
        decisions = {
            frame["box_id"]: {"status": "DECIDED", "answer": answer}
            for frame, answer in zip(frames, ["bad_geometry", "duplicate", "extra_box"])
        }
        decisions["photo_r2_coverage"] = {"status": "DECIDED", "answer": "missing_yes"}
        result = {**aggregate(record, decisions), "decisions": decisions}
        self.assertEqual(accepted_frames(record, result, {1, 2}), frames[:1])
        record["candidate_boxes"] = []
        empty = {**aggregate(record, decisions), "decisions": decisions}
        self.assertEqual(accepted_frames(record, empty, {1, 2}), [])

    def test_moderation_and_asynchronous_open_survive_restart(self):
        setup(self.api)
        db = self.api.db
        identity = self.api.get("pool:validation_exam")["id"]
        db.execute("DELETE FROM launch_queue WHERE resource_id<>?", (identity,))
        state = {"moderation": True, "open": False}
        log = []

        def request(method, path, payload=None):
            log.append((method, path))
            if path.endswith("/validate"):
                return [{"type": "MUST_PASS_MODERATION", "active": state["moderation"], "blocker": True}]
            if path.startswith("/api/new/requester/poolModeration/"):
                return {"status": "READY"}
            if path.endswith("/open"):
                return {"id": "opening", "status": "RUNNING"}
            if path == "operations/opening":
                state["open"] = True
                return {"status": "SUCCESS"}
            return {"status": "OPEN" if state["open"] else "CLOSED"}

        with patch.object(self.api, "apply", True), patch.object(self.api, "request", side_effect=request):
            open_ready_pools(self.api)
            open_ready_pools(self.api)
            state["moderation"] = False
            open_ready_pools(self.api)
            open_ready_pools(self.api)
        self.assertEqual([p for m, p in log if m == "PUT"], [f"/api/new/requester/poolModeration/{identity}"])
        self.assertEqual([p for m, p in log if m == "POST"], [f"pools/{identity}/open"])
        self.assertEqual(db.execute("SELECT count(*) FROM launch_queue").fetchone()[0], 0)
