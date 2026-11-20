"""Requester-only references and photo-level IoU for the annotation exam."""

import math

from .models import iou_for_practice

AUTO_MATCH_IOU = 0.85


def photo_iou(submitted, reference):
    """Maximum one-to-one sum, divided by the larger count. Unmatched boxes score zero."""
    if not submitted or not reference:
        return float(not submitted and not reference)
    rows, columns = sorted((reference, submitted), key=len)
    if len(rows) == 1:
        return max(iou_for_practice(rows[0], b) for b in columns) / len(columns)
    # Rectangular Hungarian assignment. Each row gets a different column at minimum total cost.
    cost = [[1 - iou_for_practice(a, b) for b in columns] for a in rows]
    n, m = len(rows), len(columns)
    row_price, col_price = [0.0] * (n + 1), [0.0] * (m + 1)
    assigned = [0] * (m + 1)
    for row in range(1, n + 1):
        assigned[0] = row
        current = 0
        distance = [math.inf] * (m + 1)
        previous = [0] * (m + 1)
        visited = set()
        while assigned[current]:
            visited.add(current)
            active = assigned[current]
            step, nearest = math.inf, 0
            for col in range(1, m + 1):
                if col in visited:
                    continue
                value = cost[active - 1][col - 1] - row_price[active] - col_price[col]
                if value < distance[col]:
                    distance[col], previous[col] = value, current
                if distance[col] < step:
                    step, nearest = distance[col], col
            for col in visited:
                row_price[assigned[col]] += step
                col_price[col] -= step
            for col in range(1, m + 1):
                distance[col] -= step
            current = nearest
        while current:
            parent = previous[current]
            assigned[current] = assigned[parent]
            current = parent
    return math.fsum(1 - cost[r - 1][c - 1] for c, r in enumerate(assigned[1:], 1) if r) / m


def matching_count(edges):
    """Maximum number of distinct butterflies that can be paired along these edges."""
    assigned = {}

    def match(reference_index, visited):
        for candidate in edges[reference_index]:
            if candidate in visited:
                continue
            visited.add(candidate)
            if candidate not in assigned or match(assigned[candidate], visited):
                assigned[candidate] = reference_index
                return True
        return False

    return sum(match(index, set()) for index in range(len(edges)))


def compare_exam_photo(inputs, output, boxes, reference):
    if reference is None or any(
        inputs.get(k) != reference[k] for k in ("image_url", "fixed_boxes", "editable_annotations")
    ):
        return None
    if output.get("reviewed") is not True:
        return None
    expected = reference["reference_boxes"]
    if not boxes and not expected and output.get("empty_confirmed") is not True:
        return None
    certain_edges, possible_edges = [], []
    for gold in expected:
        overlaps = [round(iou_for_practice(gold, b), 12) for b in boxes]
        certain_edges.append([i for i, value in enumerate(overlaps) if value >= AUTO_MATCH_IOU])
        possible_edges.append([i for i, value in enumerate(overlaps) if value >= 0.50])
    certain, possible = matching_count(certain_edges), matching_count(possible_edges)
    denominator = max(len(boxes), len(expected))
    # If borderline matches cannot change the credit, a paid review has no effect.
    score = None
    if certain == possible:
        score = 100 * certain / denominator if denominator else 100
    return {
        "iou": round(photo_iou(boxes, expected), 12),
        "reference_count": len(expected),
        "certain_matches": certain,
        "possible_matches": possible,
        "score": score,
    }
