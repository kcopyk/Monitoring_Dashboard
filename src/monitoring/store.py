import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = str(ROOT / "data" / "monitoring.db")
THAI_TZ = ZoneInfo("Asia/Bangkok")


def bangkok_now_str() -> str:
    return datetime.now(THAI_TZ).strftime("%Y-%m-%d %H:%M:%S")


def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS prediction_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            predicted_class TEXT NOT NULL,
            confidence FLOAT NOT NULL,
            latency_ms FLOAT,
            brightness FLOAT,
            blur_var FLOAT,
            width INTEGER,
            height INTEGER,
            quality_warnings TEXT DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS human_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prediction_id INTEGER NOT NULL REFERENCES prediction_events(id),
            true_label TEXT NOT NULL,
            labeled_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS drift_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            embedding_score FLOAT,
            confidence_score FLOAT,
            class_score FLOAT,
            is_drift BOOLEAN DEFAULT 0,
            embedding_drifted BOOLEAN DEFAULT 0,
            confidence_drifted BOOLEAN DEFAULT 0,
            class_drifted BOOLEAN DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            alert_type TEXT NOT NULL,
            message TEXT,
            resolved BOOLEAN DEFAULT 0
        );
    """)

    conn.commit()
    conn.close()


def insert_prediction(predicted_class, confidence, latency_ms=None,
                      brightness=None, blur_var=None, width=None, height=None,
                      quality_warnings=None):

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO prediction_events (
            timestamp, predicted_class, confidence, latency_ms,
            brightness, blur_var, width, height, quality_warnings
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        bangkok_now_str(),
        predicted_class,
        confidence,
        latency_ms,
        brightness,
        blur_var,
        width,
        height,
        json.dumps(quality_warnings or [])
    ))

    prediction_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return prediction_id

def fetch_rows(query, params=()):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return rows


def count_rows(query, params=()):
    rows = fetch_rows(query, params)
    return rows[0][0] if rows else 0


def fetch_recent_predictions(limit=100):
    rows = fetch_rows(
        """
        SELECT id, timestamp, predicted_class, confidence, brightness, blur_var, quality_warnings
        FROM prediction_events
        ORDER BY timestamp DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [
        {
            "id": row[0],
            "timestamp": row[1],
            "predicted_class": row[2],
            "confidence": row[3],
            "brightness": row[4],
            "blur_var": row[5],
            "quality_warnings": json.loads(row[6] or "[]"),
        }
        for row in reversed(rows)
    ]


def insert_drift_event(embedding_score, confidence_score, class_score, is_drift,
                       embedding_drifted=False, confidence_drifted=False, class_drifted=False):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO drift_events (
            timestamp, embedding_score, confidence_score, class_score,
            is_drift, embedding_drifted, confidence_drifted, class_drifted
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            bangkok_now_str(),
            embedding_score,
            confidence_score,
            class_score,
            int(is_drift),
            int(embedding_drifted),
            int(confidence_drifted),
            int(class_drifted),
        ),
    )
    drift_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return drift_id

def recent_hours(n=24):
    now = datetime.now(THAI_TZ).replace(minute=0, second=0, microsecond=0)
    return [(now - timedelta(hours=i)).strftime("%Y-%m-%d %H:00") for i in reversed(range(n))]

def upsert_alert(alert_type, message, dedupe_hours=1):
    if dedupe_hours > 0:
        cutoff = (datetime.now(THAI_TZ) - timedelta(hours=dedupe_hours)).strftime("%Y-%m-%d %H:%M:%S")
        rows = fetch_rows(
            """
            SELECT 1 FROM alerts
            WHERE alert_type = ?
                            AND timestamp >= ?
            LIMIT 1
            """,
            (alert_type, cutoff)
        )
        if rows:
            return False
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO alerts (timestamp, alert_type, message) VALUES (?, ?, ?)",
        (bangkok_now_str(), alert_type, message)
    )
    conn.commit()
    conn.close()
    return True

def resolve_alert(alert_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE alerts SET resolved = 1 WHERE id = ?", (alert_id,))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("Database created")