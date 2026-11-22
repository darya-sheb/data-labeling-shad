import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import maximum_bipartite_matching


def iou_matrix(reference, predicted):
    def corners(boxes):
        xywh = np.asarray([
            [box["left"], box["top"], box["width"], box["height"]] for box in boxes
        ], dtype=float).reshape(-1, 4)
        return xywh[:, :2], xywh[:, :2] + xywh[:, 2:], np.prod(xywh[:, 2:], axis=1)

    ref_min, ref_max, ref_area = corners(reference)
    pred_min, pred_max, pred_area = corners(predicted)
    top_left = np.maximum(ref_min[:, None], pred_min[None, :])
    bottom_right = np.minimum(ref_max[:, None], pred_max[None, :])
    intersection = np.maximum(bottom_right - top_left, 0).prod(axis=2)
    union = ref_area[:, None] + pred_area[None, :] - intersection
    return np.divide(intersection, union, out=np.zeros_like(intersection), where=union > 0)


def summarize(rows, suffix):
    tp, fp, fn = (sum(row[f"{key}_{suffix}"] for row in rows) for key in ("tp", "fp", "fn"))
    return {
        f"tp_{suffix}": tp,
        f"fp_{suffix}": fp,
        f"fn_{suffix}": fn,
        f"precision_{suffix}": tp / (tp + fp) if tp + fp else 0.0,
        f"recall_{suffix}": tp / (tp + fn) if tp + fn else 0.0,
        f"f1_{suffix}": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0,
    }


def evaluate(photo_ids, golden, predictions):
    rows = []
    for photo_id in photo_ids:
        reference = golden[photo_id]["boxes"]
        record = predictions[photo_id]
        error = record.get("error")
        predicted = [] if error else record["boxes"]
        ious = iou_matrix(reference, predicted)
        row = {"photo_id": photo_id, "is_negative": not reference, "error": error}
        for threshold, suffix in ((0.5, "50"), (0.75, "75")):
            tp = 0
            if ious.size:
                matches = maximum_bipartite_matching(csr_matrix(ious >= threshold))
                tp = int(np.count_nonzero(matches >= 0))
            row.update({
                f"tp_{suffix}": tp, f"fp_{suffix}": len(predicted) - tp,
                f"fn_{suffix}": len(reference) - tp,
            })
        rows.append(row)

    summary = {"n_photos": len(rows), "technical_errors": sum(bool(row["error"]) for row in rows)}
    for suffix in ("50", "75"):
        summary.update(summarize(rows, suffix))
    negatives = [row for row in rows if row["is_negative"]]
    summary.update(
        n_negative_photos=len(negatives),
        negative_photos_with_fp=sum(row["fp_50"] > 0 for row in negatives),
        fp_on_negative_photos=sum(row["fp_50"] for row in negatives),
    )
    return summary, rows
