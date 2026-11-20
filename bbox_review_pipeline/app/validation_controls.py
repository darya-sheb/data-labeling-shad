"""Space full-photo controls in a pool's creation queue, including across restarts."""

import random
from collections import Counter, defaultdict

from .worker_log import event


class ValidationQueue:
    def __init__(self, api, target, controls, interval, overlap, *, page_limit=None):
        self.api = api
        self.target = target
        self.pool = api.get("pool:" + target)["id"]
        self.interval = interval
        self.overlap = overlap
        self.page_limit = page_limit
        self.bank = defaultdict(list)
        for tasks in controls:
            photo = tasks[0]["input_values"]["image_url"]
            self.bank[photo].append(tasks)
        if not self.bank or not 1 <= interval[0] <= interval[1]:
            raise ValueError("Invalid validation control bank or interval")

        self.seen = set()
        self.uses = Counter()
        self.last_control = self.last_photo = self.last_review = None
        self.count = 0
        # The same journal records successful creates in seed, routing and the staged pool builder.
        rows = api.db.execute(
            """
            SELECT id, json_extract(payload,'$.tasks[0].input_values.image_url'),
                   json_type(payload,'$.tasks[0].known_solutions') IS NOT NULL
            FROM objects WHERE kind='task-suites' AND status='DONE'
                AND json_extract(payload,'$.pool_id')=?
                AND json_extract(payload,'$.overlap')>0
            ORDER BY rowid
        """,
            (self.pool,),
        )
        for suite_id, photo, is_control in rows:
            if is_control:
                self.remember_control(suite_id, photo)
            else:
                self.remember_review(suite_id)
        self.next_gap = self.draw_gap()

    def draw_gap(self):
        return random.Random(f"gap/{self.pool}/{self.last_control}").randint(*self.interval)

    def remember_control(self, suite_id, photo):
        self.uses[photo] += 1
        self.last_control, self.last_photo = suite_id, photo
        self.count = 0

    def remember_review(self, suite_id):
        self.seen.add(suite_id)
        self.last_review = suite_id
        self.count += 1

    def add_due_control(self):
        if self.count < self.next_gap or (
            self.page_limit is not None and self.uses.total() >= self.page_limit
        ):
            return
        rng = random.Random(f"photo/{self.pool}/{self.last_review}")
        fewest = min(self.uses[photo] for photo in self.bank)
        options = sorted(photo for photo in self.bank if self.uses[photo] == fewest)
        if len(options) > 1 and self.last_photo in options:
            options.remove(self.last_photo)
        photo = rng.choice(options)
        tasks = rng.choice(self.bank[photo])
        created = self.api.create(
            f"suite:control:{self.target}:{self.last_review}",
            "task-suites",
            {
                "pool_id": self.pool,
                "tasks": tasks,
                "mixed": False,
                "overlap": self.overlap,
                "infinite_overlap": False,
            },
        )
        gap = self.count
        self.remember_control(created["id"], photo)
        self.next_gap = self.draw_gap()
        event(
            "validation.control_created",
            destination=self.target,
            suite_id=created["id"],
            image_id=tasks[0]["input_values"]["image_id"],
            ordinary_photos=gap,
            next_gap=self.next_gap,
        )

    def create_review(self, key, payload):
        # A previous run can have committed the last ordinary photo just before a control was due.
        self.add_due_control()
        stored = self.api.db.execute(
            "SELECT 1 FROM objects WHERE key=? AND status='DONE' AND json_extract(payload,'$.pool_id')=?",
            (key, self.pool),
        ).fetchone()
        review = self.api.get(key) if stored else self.api.create(key, "task-suites", payload)
        if review["id"] not in self.seen and (review["overlap"]):
            self.remember_review(review["id"])
            self.add_due_control()
        return review
