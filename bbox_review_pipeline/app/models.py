import math
from collections import Counter


def box(values):
    if len(values) != 4 or any(
        type(v) not in (int, float) or not math.isfinite(v) or v < 0 or v > 1 for v in values
    ):
        raise ValueError("Coordinates must be four finite numbers in [0,1]")
    if values[0] >= values[2] or values[1] >= values[3]:
        raise ValueError("Rectangle must have positive width and height")
    return list(values)


def annotation(b):
    x1, y1, x2, y2 = box(b)
    return {"type": "rectangle", "data": {"p1": {"x": x1, "y": y1}, "p2": {"x": x2, "y": y2}}}


def from_annotation(a):
    if a.get("type") != "rectangle":
        raise ValueError("Only rectangles are allowed")
    p, q = a["data"]["p1"], a["data"]["p2"]
    coords = [p["x"], p["y"], q["x"], q["y"]]
    if any(type(v) not in (int, float) or not math.isfinite(v) or not -1e-6 <= v <= 1 + 1e-6 for v in coords):
        raise ValueError("Invalid rectangle coordinates")
    x1, y1, x2, y2 = [max(0, min(1, v)) for v in coords]
    return box([min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)])


def iou_for_practice(a, b):
    a, b = box(a), box(b)
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return intersection / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection)


def candidates(image, revision, boxes):
    return [{"box_id": f"{image}_r{revision}_b{i}", "bbox": bounds} for i, bounds in enumerate(boxes)]


def ordered_boxes(record):
    # Draw accepted references below the candidates.
    return [{**b, "fixed": True} for b in record.get("fixed_boxes", [])] + [
        {**b, "fixed": False} for b in record["candidate_boxes"]
    ]


def intersects(a, b):
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def review_tasks(record):
    """Ask about each candidate in source order, then coverage. Fixed frames are context only."""
    context = ordered_boxes(record)
    tasks = []
    for index, b in enumerate(record["candidate_boxes"]):
        tasks.append(
            {
                "input_values": {
                    "review_item_id": b["box_id"],
                    "review_type": "box",
                    "image_id": record["image_id"],
                    "revision": record["revision"],
                    "image_url": record["image_url"],
                    "focus_box_id": b["box_id"],
                    "focus_bbox": b["bbox"],
                    "box_index": index,
                    "box_count": len(record["candidate_boxes"]),
                    "context_boxes": context,
                }
            }
        )
    tasks.append(
        {
            "input_values": {
                "review_item_id": f"{record['image_id']}_r{record['revision']}_coverage",
                "review_type": "coverage",
                "image_id": record["image_id"],
                "revision": record["revision"],
                "image_url": record["image_url"],
                "focus_box_id": "",
                "focus_bbox": [],
                "context_boxes": context,
            }
        }
    )
    return tasks


def review_suite(pool_id, record, overlap):
    authors = set(record.get("source_annotation_worker_ids", []))
    model_origin = (
        record.get("source") == "model"
        and record["revision"] == 1
        and not record.get("annotation_assignment_id")
        and not record.get("annotation_worker_id")
    )
    if not authors and not model_origin:
        raise ValueError("Real human annotation requires author IDs; refusing unsafe validation")
    return {
        "pool_id": pool_id,
        "tasks": review_tasks(record),
        "mixed": False,
        "overlap": overlap,
        "infinite_overlap": False,
        "unavailable_for": sorted(authors),
    }


def validation_solutions(answer):
    values = (
        [{"answer": answer, "duplicate_reason": reason} for reason in ("fixed", "earlier")]
        if answer == "duplicate"
        else [{"answer": answer}]
    )
    return [{"output_values": value, "correctness_weight": 1} for value in values]


def confirmed_empty_photo(record):
    return (
        record.get("empty_confirmed") is True
        and not record["candidate_boxes"]
        and not record.get("fixed_boxes")
    )


def item_decisions(record, votes, minimum=2):
    """Count independent votes on each candidate in order, followed by whole-photo coverage."""
    tasks = review_tasks(record)
    excluded = set(record.get("source_annotation_worker_ids", []))
    decisions = {}
    for task in tasks:
        item = task["input_values"]["review_item_id"]
        allowed = (
            {"missing_no", "missing_yes"}
            if task["input_values"]["review_type"] == "coverage"
            else {"box_correct", "bad_geometry", "extra_box", "duplicate"}
        )
        unique = {}
        invalid = set()
        for worker, answer in votes.get(item, []):
            if worker not in excluded and answer in allowed:
                if worker in unique and unique[worker] != answer:
                    invalid.add(worker)
                unique[worker] = answer
        # Replacements for another question on the photo do not add surplus ballots here.
        unique = dict([(w, a) for w, a in unique.items() if w not in invalid][: minimum + 1])
        count = len(unique)
        answer = None
        if count >= minimum:
            winner, support = Counter(unique.values()).most_common(1)[0]
            if support * 2 > count:
                answer = winner
        status = "DECIDED" if answer else "WAITING_VOTES" if count < minimum + 1 else "NEEDS_ANNOTATION"
        decisions[item] = {"answer": answer, "status": status, "vote_count": count, "workers": sorted(unique)}
        if task["input_values"]["review_type"] == "coverage":
            decisions[item]["missing_reported_by"] = sorted(
                w for w, a in unique.items() if a == "missing_yes"
            )
    return decisions


def aggregate(record, decisions):
    """Keep correct frames, drop extras and duplicates, and return editable geometry for corrections."""
    fixed = [{k: v for k, v in b.items() if k != "fixed"} for b in record.get("fixed_boxes", [])]
    editable, waiting, conflicting = [], [], []
    removed_duplicates = []
    duplicate_of = {}
    geometry_frames, disputed_frames = [], []
    for index, b in enumerate(record["candidate_boxes"]):
        decision = decisions[b["box_id"]]
        if decision["status"] == "WAITING_VOTES":
            waiting.append(b["box_id"])
        elif decision["answer"] == "box_correct":
            fixed.append({k: v for k, v in b.items() if k != "fixed"})
        elif decision["answer"] == "duplicate":
            if index == 0 and not record.get("fixed_boxes"):
                # Inconsistent legacy votes: no red or earlier frame existed.
                editable.append(b["bbox"])
                conflicting.append(b["box_id"])
                disputed_frames.append(len(editable))
                continue
            removed_duplicates.append(b["box_id"])
            # Optional audit link only. A human-confirmed repeat is removed even
            # if the earlier frame needs correction or several butterflies overlap.
            anchors = [a for a in fixed if intersects(a["bbox"], b["bbox"])]
            if len(anchors) == 1 and not any(intersects(coords, b["bbox"]) for coords in editable):
                duplicate_of[b["box_id"]] = anchors[0]["box_id"]
        elif decision["answer"] == "bad_geometry" or decision["status"] == "NEEDS_ANNOTATION":
            editable.append(b["bbox"])
            if decision["status"] == "NEEDS_ANNOTATION":
                conflicting.append(b["box_id"])
                disputed_frames.append(len(editable))
            else:
                geometry_frames.append(len(editable))
        # extra_box means there is no butterfly, never a duplicate.
    coverage_id = f"{record['image_id']}_r{record['revision']}_coverage"
    coverage = decisions[coverage_id]
    if coverage["status"] == "WAITING_VOTES":
        waiting.append(coverage_id)
    # A repeat indicates at least one butterfly. If the votes removed every
    # frame, request a fresh box without handing the deleted copy back.
    needs_annotation = bool(
        editable
        or conflicting
        or (removed_duplicates and not fixed)
        or coverage["answer"] == "missing_yes"
        or coverage["status"] == "NEEDS_ANNOTATION"
    )
    result = {
        "image_id": record["image_id"],
        "revision": record["revision"],
        "fixed_boxes": fixed,
        "editable_boxes": editable,
        "status": "WAITING_VALIDATION" if waiting else "NEEDS_ANNOTATION" if needs_annotation else "FINAL",
        "unresolved": waiting,
        "conflicting": conflicting,
        "removed_duplicates": removed_duplicates,
        "duplicate_of": duplicate_of,
    }
    if result["status"] == "NEEDS_ANNOTATION":
        result["correction_feedback"] = {
            "geometry_frames": geometry_frames,
            "disputed_frames": disputed_frames,
            "coverage": coverage["answer"],
            "redraw_after_duplicate": bool(removed_duplicates and not fixed),
        }
    return result


def accepted_frames(record, result, rejected_revisions):
    """Keep surviving boxes at their submitted coordinates after two rejected revisions."""
    if (
        result["status"] != "NEEDS_ANNOTATION"
        or len(set(rejected_revisions)) < 2
        or record["revision"] not in rejected_revisions
    ):
        return []
    return result["fixed_boxes"] + [
        frame
        for frame in record["candidate_boxes"]
        if result["decisions"][frame["box_id"]]["answer"] == "bad_geometry"
        or frame["box_id"] in result["conflicting"]
    ]


def work_photo_score(record, decisions, result):
    """Give equal weight to each submitted box and the single coverage verdict."""
    if result["status"] == "WAITING_VALIDATION" or result["conflicting"]:
        return None
    coverage = decisions[f"{record['image_id']}_r{record['revision']}_coverage"]["answer"]
    box_answers = [decisions[b["box_id"]]["answer"] for b in record["candidate_boxes"]]
    if coverage not in ("missing_no", "missing_yes") or None in box_answers:
        return None
    correct_boxes = box_answers.count("box_correct")
    coverage_point = int(coverage == "missing_no")
    return 100 * (correct_boxes + coverage_point) / (len(box_answers) + 1)


def exam_photo_score(record, decisions):
    """A tied criterion earns half credit once the deciding reviewer has answered."""
    coverage = f"{record['image_id']}_r{record['revision']}_coverage"
    if any(d["status"] == "WAITING_VOTES" for d in decisions.values()):
        return None
    answers = [decisions[b["box_id"]]["answer"] for b in record["candidate_boxes"]]
    correct = answers.count("box_correct") + 0.5 * answers.count(None)
    # A coverage answer reports presence of a miss, not how many were missed.
    represented = sum(a in ("box_correct", "bad_geometry") for a in answers)
    missed = int(decisions[coverage]["answer"] == "missing_yes")
    total = max(len(answers), record.get("reference_count", 0), represented + missed)
    return 100 * correct / total if total else 100
