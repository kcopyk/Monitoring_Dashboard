"""Seed the monitoring.db with realistic mock data for local demos.

Usage examples:
    python scripts/seed_mock_data.py --reset
    python scripts/seed_mock_data.py --hours 168 --per-hour 12 --label-rate 0.4 --reset --seed 42
"""

import argparse
import json
import random
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure src/ is on the import path when running the script directly
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.monitoring.store import DB_PATH, init_db


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _quality_flags(brightness: float, blur_var: float) -> list[str]:
    flags: list[str] = []
    if brightness < 40:
        flags.append("low_brightness")
    if blur_var < 50:
        flags.append("blurry")
    return flags


def _traffic_multiplier(hour_of_day: int) -> float:
    # lunchtime and evening snack periods are busier than early morning
    if 11 <= hour_of_day <= 13:
        return 1.35
    if 18 <= hour_of_day <= 21:
        return 1.25
    if 0 <= hour_of_day <= 6:
        return 0.65
    return 1.0


def _class_weights(hour_of_day: int) -> tuple[float, float]:
    # beverages peak midday, snacks peak slightly in late evening
    if 11 <= hour_of_day <= 15:
        return 0.62, 0.38
    if 19 <= hour_of_day <= 22:
        return 0.48, 0.52
    return 0.55, 0.45


def _confidence_profile(hour_of_day: int) -> tuple[float, float]:
    # lower confidence during low-light/night windows
    if 0 <= hour_of_day <= 6:
        return 0.86, 0.06
    if 18 <= hour_of_day <= 23:
        return 0.89, 0.05
    return 0.92, 0.04


def seed_predictions(cursor: sqlite3.Cursor, start_at: datetime, hours: int, per_hour: int) -> list[dict]:
    """Insert synthetic prediction rows spanning the last N hours."""
    predictions: list[dict] = []
    classes = ["beverages", "snacks"]

    for i in range(hours):
        hour_start = start_at + timedelta(hours=i)
        hour_of_day = hour_start.hour
        traffic = _traffic_multiplier(hour_of_day)
        hour_count = max(6, int(round(per_hour * traffic + random.randint(-2, 2))))
        bev_w, snk_w = _class_weights(hour_of_day)
        conf_mu, conf_sigma = _confidence_profile(hour_of_day)

        for _ in range(hour_count):
            ts = hour_start + timedelta(
                minutes=random.randint(0, 59), seconds=random.randint(0, 59)
            )

            predicted_class = random.choices(classes, weights=[bev_w, snk_w], k=1)[0]

            # Keep confidence stable for most hours with occasional mild drops.
            if random.random() < (0.04 if hour_of_day >= 7 else 0.08):
                confidence = _clip(random.gauss(0.56, 0.08), 0.2, 0.86)
            else:
                confidence = _clip(random.gauss(conf_mu, conf_sigma), 0.45, 0.995)

            latency_ms = _clip(random.gauss(175 + (12 if hour_of_day <= 6 else 0), 55), 40, 550)

            quality_issue_prob = 0.04 if 7 <= hour_of_day <= 17 else 0.08
            if random.random() < quality_issue_prob:
                brightness = _clip(random.gauss(34, 7), 8, 100)
                blur_var = _clip(random.gauss(42, 14), 8, 180)
            else:
                brightness = _clip(random.gauss(86, 14), 30, 150)
                blur_var = _clip(random.gauss(165, 34), 45, 340)

            width = random.choice([640, 720, 1080])
            height = 480 if width == 640 else 720

            quality_warnings = _quality_flags(brightness, blur_var)

            cursor.execute(
                """
                INSERT INTO prediction_events (
                    timestamp, predicted_class, confidence, latency_ms,
                    brightness, blur_var, width, height, quality_warnings
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts.isoformat(sep=" ", timespec="seconds"),
                    predicted_class,
                    confidence,
                    latency_ms,
                    brightness,
                    blur_var,
                    width,
                    height,
                    json.dumps(quality_warnings),
                ),
            )

            predictions.append(
                {
                    "id": cursor.lastrowid,
                    "timestamp": ts,
                    "predicted_class": predicted_class,
                    "confidence": confidence,
                }
            )
    return predictions


def seed_feedback(cursor: sqlite3.Cursor, predictions: list[dict], label_rate: float = 0.35) -> int:
    """Attach human feedback to a subset of predictions."""
    labeled = 0
    for pred in predictions:
        if random.random() > label_rate:
            continue
        predicted = pred["predicted_class"]
        # Introduce some disagreement for realism.
        if random.random() < 0.12:
            true_label = "snacks" if predicted == "beverages" else "beverages"
        else:
            true_label = predicted

        cursor.execute(
            """
            INSERT INTO human_feedback (prediction_id, true_label, labeled_at)
            VALUES (?, ?, ?)
            """,
            (
                pred["id"],
                true_label,
                pred["timestamp"].isoformat(sep=" ", timespec="seconds"),
            ),
        )
        labeled += 1
    return labeled


def seed_drift_events(cursor: sqlite3.Cursor, start_at: datetime, hours: int) -> list[dict]:
    """Insert hourly drift events that stay high (0.8-0.9) with short drops."""
    events: list[dict] = []
    drop_remaining = 0
    drop_cooldown = 0
    for i in range(hours):
        ts = start_at + timedelta(hours=i)

        if drop_remaining == 0 and drop_cooldown == 0 and random.random() < 0.1:
            drop_remaining = random.randint(1, 2)

        if drop_remaining > 0:
            embedding_score = _clip(random.gauss(0.53, 0.05), 0.36, 0.68)
            confidence_score = _clip(random.gauss(0.55, 0.05), 0.36, 0.70)
            class_score = _clip(random.gauss(0.5, 0.06), 0.32, 0.68)
            drop_remaining -= 1
            if drop_remaining == 0:
                drop_cooldown = 4
        else:
            embedding_score = _clip(random.gauss(0.86, 0.035), 0.78, 0.93)
            confidence_score = _clip(random.gauss(0.87, 0.035), 0.79, 0.94)
            class_score = _clip(random.gauss(0.84, 0.04), 0.74, 0.92)
            if drop_cooldown > 0:
                drop_cooldown -= 1

        embedding_drifted = embedding_score > 0.55
        confidence_drifted = confidence_score > 0.55
        class_drifted = class_score > 0.55
        is_drift = embedding_drifted or confidence_drifted or class_drifted

        cursor.execute(
            """
            INSERT INTO drift_events (
                timestamp, embedding_score, confidence_score, class_score,
                is_drift, embedding_drifted, confidence_drifted, class_drifted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ts.isoformat(sep=" ", timespec="seconds"),
                embedding_score,
                confidence_score,
                class_score,
                int(is_drift),
                int(embedding_drifted),
                int(confidence_drifted),
                int(class_drifted),
            ),
        )

        events.append(
            {
                "timestamp": ts,
                "is_drift": is_drift,
                "embedding_score": embedding_score,
                "confidence_score": confidence_score,
                "class_score": class_score,
            }
        )
    return events


def seed_alerts(cursor: sqlite3.Cursor, predictions: list[dict], drift_events: list[dict]) -> int:
    inserted = 0

    alerts: list[tuple[str, str, datetime, int]] = []

    # rolling window scans produce naturally spaced alerts across types
    window = 120
    step = 40
    for start in range(0, max(1, len(predictions) - window + 1), step):
        chunk = predictions[start : start + window]
        if not chunk:
            continue

        low_conf_share = sum(p["confidence"] < 0.6 for p in chunk) / len(chunk)
        chunk_end = chunk[-1]["timestamp"].replace(tzinfo=timezone.utc)

        if low_conf_share >= 0.33:
            alerts.append(
                (
                    "low_confidence_spike",
                    f"Low-confidence spike reached {low_conf_share:.0%} in recent serving window",
                    chunk_end,
                    0,
                )
            )

    drift_times = [e["timestamp"].replace(tzinfo=timezone.utc) for e in drift_events if e["is_drift"]]
    for ts in drift_times[-3:]:
        alerts.append(
            (
                "drift_detected",
                "Drift detected across at least one monitored dimension",
                ts,
                0,
            )
        )

    quality_drop_points = sorted([p for p in predictions if p["confidence"] < 0.45], key=lambda p: p["timestamp"])[:2]
    for point in quality_drop_points:
        alerts.append(
            (
                "image_quality_drop",
                "Image quality dropped in camera feed (blur/brightness anomaly)",
                point["timestamp"].replace(tzinfo=timezone.utc),
                1,
            )
        )

    # Deduplicate nearby alerts of same type and keep timeline tidy
    alerts.sort(key=lambda x: x[2])
    deduped: list[tuple[str, str, datetime, int]] = []
    for alert_type, message, ts, resolved in alerts:
        if deduped and deduped[-1][0] == alert_type and (ts - deduped[-1][2]) < timedelta(hours=1):
            continue
        deduped.append((alert_type, message, ts, resolved))

    for alert_type, message, ts, resolved in deduped[-10:]:
        cursor.execute(
            """
            INSERT INTO alerts (timestamp, alert_type, message, resolved)
            VALUES (?, ?, ?, ?)
            """,
            (ts.replace(tzinfo=None).isoformat(sep=" ", timespec="seconds"), alert_type, message, resolved),
        )
        inserted += 1
    return inserted


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed monitoring.db with mock data")
    parser.add_argument("--hours", type=int, default=72, help="Span of hours to backfill")
    parser.add_argument("--per-hour", dest="per_hour", type=int, default=18, help="Predictions per hour")
    parser.add_argument("--label-rate", dest="label_rate", type=float, default=0.35, help="Probability a prediction is labeled")
    parser.add_argument("--reset", action="store_true", help="Clear existing rows before seeding")
    parser.add_argument("--seed", type=int, help="Random seed for reproducibility")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    init_db()
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if args.reset:
        cursor.executescript(
            """
            DELETE FROM human_feedback;
            DELETE FROM prediction_events;
            DELETE FROM drift_events;
            DELETE FROM alerts;
            VACUUM;
            """
        )

    start_at = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0, tzinfo=None) - timedelta(hours=args.hours - 1)

    predictions = seed_predictions(cursor, start_at, args.hours, args.per_hour)
    labeled = seed_feedback(cursor, predictions, label_rate=args.label_rate)
    drift_events = seed_drift_events(cursor, start_at, args.hours)
    alerts = seed_alerts(cursor, predictions, drift_events)

    conn.commit()
    conn.close()

    print(
        f"Seeded {len(predictions)} predictions, {labeled} labels, {len(drift_events)} drift events, {alerts} alerts"
    )


if __name__ == "__main__":
    main()
