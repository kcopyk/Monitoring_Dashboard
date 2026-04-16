from collections import Counter

from src.monitoring.store import (
    count_rows,
    fetch_recent_predictions,
    insert_drift_event,
    upsert_alert,
)


WINDOW_SIZE = 100
LOW_CONFIDENCE_THRESHOLD = 0.6
DRIFT_THRESHOLD = 0.55
LOW_CONFIDENCE_SPIKE_THRESHOLD = 0.25
QUALITY_DROP_THRESHOLD = 0.20


def _quality_issue_ratio(rows):
    if not rows:
        return 0.0

    flagged = 0
    for row in rows:
        warnings = row.get("quality_warnings") or []
        brightness = row.get("brightness")
        blur_var = row.get("blur_var")
        if warnings:
            flagged += 1
            continue
        if brightness is not None and brightness < 40:
            flagged += 1
            continue
        if blur_var is not None and blur_var < 50:
            flagged += 1
    return flagged / len(rows)


def _class_drift_score(rows):
    if not rows:
        return 0.0

    counts = Counter(row["predicted_class"] for row in rows)
    beverages_ratio = counts.get("beverages", 0) / len(rows)
    snacks_ratio = counts.get("snacks", 0) / len(rows)
    return abs(beverages_ratio - snacks_ratio)


def run_orchestrator_from_db() -> dict:
    total_predictions = count_rows("SELECT COUNT(*) FROM prediction_events")
    if total_predictions < WINDOW_SIZE:
        return {
            "checked": False,
            "reason": "window_not_full",
            "total_predictions": total_predictions,
            "window_size": WINDOW_SIZE,
        }

    if total_predictions % WINDOW_SIZE != 0:
        return {
            "checked": False,
            "reason": "not_a_window_boundary",
            "total_predictions": total_predictions,
            "window_size": WINDOW_SIZE,
        }

    recent_rows = fetch_recent_predictions(WINDOW_SIZE)
    if len(recent_rows) < WINDOW_SIZE:
        return {
            "checked": False,
            "reason": "insufficient_window_rows",
            "total_predictions": total_predictions,
            "window_size": WINDOW_SIZE,
        }

    low_confidence_ratio = sum(row["confidence"] < LOW_CONFIDENCE_THRESHOLD for row in recent_rows) / len(recent_rows)
    quality_drop_ratio = _quality_issue_ratio(recent_rows)
    class_score = _class_drift_score(recent_rows)

    embedding_score = quality_drop_ratio
    confidence_score = low_confidence_ratio

    embedding_drifted = embedding_score >= DRIFT_THRESHOLD
    confidence_drifted = confidence_score >= DRIFT_THRESHOLD
    class_drifted = class_score >= DRIFT_THRESHOLD
    is_drift = embedding_drifted or confidence_drifted or class_drifted

    drift_id = insert_drift_event(
        embedding_score=embedding_score,
        confidence_score=confidence_score,
        class_score=class_score,
        is_drift=is_drift,
        embedding_drifted=embedding_drifted,
        confidence_drifted=confidence_drifted,
        class_drifted=class_drifted,
    )

    alert_messages = []
    if is_drift:
        alert_messages.append(
            (
                "drift_detected",
                f"Drift detected in the last {WINDOW_SIZE} predictions: embedding={embedding_score:.2f}, confidence={confidence_score:.2f}, class={class_score:.2f}",
            )
        )
    if low_confidence_ratio >= LOW_CONFIDENCE_SPIKE_THRESHOLD:
        alert_messages.append(
            (
                "low_confidence_spike",
                f"Low-confidence spike: {low_confidence_ratio:.0%} of the last {WINDOW_SIZE} predictions fell below {LOW_CONFIDENCE_THRESHOLD:.1f}",
            )
        )
    if quality_drop_ratio >= QUALITY_DROP_THRESHOLD:
        alert_messages.append(
            (
                "image_quality_drop",
                f"Image quality drop: {quality_drop_ratio:.0%} of the last {WINDOW_SIZE} predictions had low-quality signals",
            )
        )

    for alert_type, message in alert_messages:
        upsert_alert(alert_type, message)

    return {
        "checked": True,
        "total_predictions": total_predictions,
        "drift_event_id": drift_id,
        "scores": {
            "embedding": round(embedding_score, 4),
            "confidence": round(confidence_score, 4),
            "class": round(class_score, 4),
        },
        "alerts_created": [alert_type for alert_type, _ in alert_messages],
    }