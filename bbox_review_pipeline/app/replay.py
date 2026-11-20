"""Recompute the delivered dataset from anonymous ballots on the last issued revisions."""

import json

from .api import ROOT
from .export import write_golden
from .materials import model_record, photos_for_review
from .models import accepted_frames, aggregate, candidates, item_decisions, review_tasks


def replay(output):
    photos = {p["image_id"]: p for p in photos_for_review()}
    results = []
    for line in (ROOT / "reference/final_votes.jsonl").read_text().splitlines():
        page = json.loads(line)
        image = str(page["photo_id"])
        record = model_record(photos[image])
        if "revision" in page:
            revision = page["revision"]
            record.update(
                revision=revision,
                candidate_boxes=candidates(image, revision, page["editable"]),
                fixed_boxes=[
                    {"box_id": f"fixed-{i}", "bbox": bounds} for i, bounds in enumerate(page["fixed"])
                ],
            )
        items = [t["input_values"]["review_item_id"] for t in review_tasks(record)]
        votes = {item: [] for item in items}
        for reviewer, ballot in enumerate(page["votes"]):
            for item, answer in zip(items, ballot, strict=True):
                if answer is not None:
                    votes[item].append((reviewer, answer))
        decisions = item_decisions(record, votes)
        result = aggregate(record, decisions)
        if "accepted_after_rejections" in page:
            result["decisions"] = decisions
            frames = accepted_frames(record, result, page["accepted_after_rejections"])
            if not frames:
                raise ValueError(f"Нет оснований для приёмки версии фото {image}")
            result.update(status="FINAL", fixed_boxes=frames, editable_boxes=[])
        results.append({**result, "source_image_id": image})
    return write_golden(set(photos), results, output)
