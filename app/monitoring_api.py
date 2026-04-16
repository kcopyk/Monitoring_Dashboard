from collections import OrderedDict
import json
import sqlite3

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from src.monitoring.store import DB_PATH, count_rows, recent_hours, resolve_alert

router = APIRouter(prefix="/monitoring", tags=["Monitoring"])


class LabelRequest(BaseModel):
    true_label: str


class QueryRequest(BaseModel):
    sql: str


def _is_read_only_query(sql: str) -> bool:
    statement = sql.strip().lower()
    return statement.startswith(("select", "with", "pragma", "explain"))


def _run_sql_query(sql: str):
    if not _is_read_only_query(sql):
        raise HTTPException(status_code=400, detail="Only read-only SQL is allowed in the browser query tool")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        rows = cursor.fetchall()
        columns = list(rows[0].keys()) if rows else [description[0] for description in cursor.description or []]
        return {
            "columns": columns,
            "rows": [[row[column] for column in columns] for row in rows],
            "row_count": len(rows),
        }
    finally:
        conn.close()


@router.get("/db-web", response_class=HTMLResponse)
def db_web_preview(limit: int = 25):
    limit = max(5, min(limit, 100))
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    tables = {
        "prediction_events": [
            "id", "timestamp", "predicted_class", "confidence", "latency_ms",
            "brightness", "blur_var", "width", "height", "quality_warnings",
        ],
        "human_feedback": ["id", "prediction_id", "true_label", "labeled_at"],
        "drift_events": [
            "id", "timestamp", "embedding_score", "confidence_score", "class_score",
            "is_drift", "embedding_drifted", "confidence_drifted", "class_drifted",
        ],
        "alerts": ["id", "timestamp", "alert_type", "message", "resolved"],
    }

    blocks = []
    for table_name, columns in tables.items():
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        total = cursor.fetchone()[0]
        order_by = "labeled_at DESC, id DESC" if table_name == "human_feedback" else "id DESC"
        cursor.execute(
            f"SELECT {', '.join(columns)} FROM {table_name} ORDER BY {order_by} LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()

        header_html = "".join(f"<th>{col}</th>" for col in columns)
        rows_html = "".join(
            "<tr>" + "".join(f"<td>{str(cell)}</td>" for cell in row) + "</tr>"
            for row in rows
        )
        blocks.append(
            f"""
            <section class='card'>
                <h2>{table_name}</h2>
                <p class='meta'>total rows: <strong>{total}</strong> | showing latest <strong>{len(rows)}</strong></p>
                <div class='table-wrap'>
                    <table>
                        <thead><tr>{header_html}</tr></thead>
                        <tbody>{rows_html or '<tr><td colspan="20">No rows</td></tr>'}</tbody>
                    </table>
                </div>
            </section>
            """
        )

    conn.close()

    return f"""
    <!doctype html>
    <html>
        <head>
            <meta charset='utf-8' />
            <meta name='viewport' content='width=device-width,initial-scale=1' />
            <title>Monitoring DB Preview</title>
            <style>
                body {{
                    margin: 0;
                    font-family: ui-sans-serif, -apple-system, Segoe UI, Roboto, sans-serif;
                    background: linear-gradient(180deg, #f8fafc, #f1f5f9);
                    color: #0f172a;
                }}
                .container {{ max-width: 1500px; margin: 0 auto; padding: 20px; }}
                h1 {{ margin: 0 0 14px; }}
                .sub {{ color: #475569; margin: 0 0 16px; }}
                .query-box {{
                    display: grid;
                    gap: 10px;
                    margin-bottom: 16px;
                }}
                .query-input {{
                    width: 100%;
                    min-height: 120px;
                    padding: 12px;
                    border-radius: 12px;
                    border: 1px solid #cbd5e1;
                    font: inherit;
                    resize: vertical;
                    box-sizing: border-box;
                }}
                .query-row {{
                    display: flex;
                    gap: 10px;
                    flex-wrap: wrap;
                    align-items: center;
                }}
                .query-btn {{
                    background: #0f766e;
                    color: white;
                    border: none;
                    border-radius: 10px;
                    padding: 10px 14px;
                    font-weight: 700;
                    cursor: pointer;
                }}
                .query-btn:hover {{ background: #115e59; }}
                .query-note {{ color: #64748b; font-size: 13px; }}
                .query-result {{ margin-top: 12px; }}
                .card {{
                    background: white;
                    border: 1px solid #cbd5e1;
                    border-radius: 14px;
                    padding: 14px;
                    margin-bottom: 16px;
                    box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
                }}
                .meta {{ color: #475569; margin: 2px 0 12px; font-size: 14px; }}
                .table-wrap {{ overflow-x: auto; }}
                table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
                th, td {{ border-bottom: 1px solid #e2e8f0; text-align: left; padding: 8px 10px; white-space: nowrap; }}
                th {{ background: #f8fafc; position: sticky; top: 0; }}
                .error {{ color: #b91c1c; font-weight: 700; }}
            </style>
        </head>
        <body>
            <div class='container'>
                <h1>Monitoring Database Preview</h1>
                <p class='sub'>SQLite browser for <strong>data/monitoring.db</strong>. You can run read-only SQL queries here.</p>
                <div class='card query-box'>
                    <div>
                        <label for='sql'><strong>SQL query</strong></label>
                        <textarea id='sql' class='query-input'>SELECT * FROM prediction_events ORDER BY id DESC LIMIT 10;</textarea>
                    </div>
                    <div class='query-row'>
                        <button class='query-btn' id='run-btn'>Run query</button>
                        <span class='query-note'>Allowed: SELECT, WITH, PRAGMA, EXPLAIN. Example: SELECT * FROM alerts ORDER BY timestamp DESC LIMIT 20;</span>
                    </div>
                    <div id='query-meta' class='query-note'>No query run yet.</div>
                    <div id='query-error' class='error'></div>
                    <div id='query-result' class='query-result'></div>
                </div>
                {''.join(blocks)}
            </div>
            <script>
                const sqlEl = document.getElementById('sql');
                const runBtn = document.getElementById('run-btn');
                const resultEl = document.getElementById('query-result');
                const metaEl = document.getElementById('query-meta');
                const errorEl = document.getElementById('query-error');

                function renderTable(payload) {{
                    if (!payload.rows.length) {{
                        resultEl.innerHTML = '<p class="query-note">Query returned 0 rows.</p>';
                        return;
                    }}

                    const head = payload.columns.map((col) => `<th>${{col}}</th>`).join('');
                    const body = payload.rows.map((row) =>
                        '<tr>' + row.map((cell) => `<td>${{cell === null || cell === undefined ? '' : String(cell)}}</td>`).join('') + '</tr>'
                    ).join('');

                    resultEl.innerHTML = `
                        <div class='card'>
                            <p class='meta'>Rows returned: <strong>${{payload.row_count}}</strong></p>
                            <div class='table-wrap'>
                                <table>
                                    <thead><tr>${{head}}</tr></thead>
                                    <tbody>${{body}}</tbody>
                                </table>
                            </div>
                        </div>
                    `;
                }}

                async function runQuery() {{
                    errorEl.textContent = '';
                    resultEl.innerHTML = '';
                    metaEl.textContent = 'Running query...';
                    runBtn.disabled = true;

                    try {{
                        const response = await fetch('/monitoring/db-query', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify({{ sql: sqlEl.value }})
                        }});
                        const payload = await response.json();
                        if (!response.ok) {{
                            throw new Error(payload.detail || 'Query failed');
                        }}
                        metaEl.textContent = 'Query completed successfully.';
                        renderTable(payload);
                    }} catch (error) {{
                        metaEl.textContent = 'Query failed.';
                        errorEl.textContent = error.message || String(error);
                    }} finally {{
                        runBtn.disabled = false;
                    }}
                }}

                runBtn.addEventListener('click', runQuery);
                sqlEl.addEventListener('keydown', (event) => {{
                    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {{
                        runQuery();
                    }}
                }});
            </script>
        </body>
    </html>
    """


@router.post("/db-query")
def db_query(payload: QueryRequest):
    return _run_sql_query(payload.sql)


# ---------------- KPI ----------------
@router.get("/kpi")
def get_kpi():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM prediction_events WHERE DATE(timestamp) = DATE('now')")
    total_today = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) FROM prediction_events
        WHERE confidence < 0.6 AND timestamp >= datetime('now', '-24 hours')
    """)
    low_conf = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM prediction_events WHERE timestamp >= datetime('now', '-24 hours')")
    total_24h = cursor.fetchone()[0]
    low_conf_rate = low_conf / total_24h if total_24h > 0 else 0

    cursor.execute("""
        SELECT COUNT(*) FROM drift_events
        WHERE is_drift = 1 AND timestamp >= datetime('now', '-24 hours')
    """)
    drift_count = cursor.fetchone()[0]
    drift_status = "พบ Drift" if drift_count > 0 else "ปกติ"

    cursor.execute("SELECT COUNT(*) FROM alerts WHERE resolved = 0")
    active_alerts = cursor.fetchone()[0]

    conn.close()
    return {
        "drift_status": drift_status,
        "low_confidence_rate": low_conf_rate,
        "total_requests_today": total_today,
        "active_alerts": active_alerts,
    }


# ---------------- Confidence Over Time (real) ----------------
@router.get("/confidence-trend")
def confidence_trend():
    hours = recent_hours(24)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT strftime('%Y-%m-%d %H:00', timestamp) AS h, AVG(confidence)
        FROM prediction_events
        WHERE timestamp >= datetime('now', '-24 hours')
        GROUP BY h
    """)
    rows = {r[0]: r[1] for r in cursor.fetchall()}
    conn.close()
    data = [{"hour": h[-5:], "avg_confidence": round(rows.get(h, 0), 3)} for h in hours]
    return {"threshold": 0.6, "points": data}


# ---------------- Class Ratio Over Time ----------------
@router.get("/class-ratio")
def class_ratio():
    hours = recent_hours(24)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT strftime('%Y-%m-%d %H:00', timestamp) AS h, predicted_class, COUNT(*)
        FROM prediction_events
        WHERE timestamp >= datetime('now', '-24 hours')
        GROUP BY h, predicted_class
    """)
    raw = cursor.fetchall()
    conn.close()

    agg = {h: {"beverages": 0, "snacks": 0} for h in hours}
    for h, cls, cnt in raw:
        if h in agg and cls in agg[h]:
            agg[h][cls] = cnt
    data = [{"hour": h[-5:], "beverages": agg[h]["beverages"], "snacks": agg[h]["snacks"]} for h in hours]
    return data


# ---------------- Drift Score Trend ----------------
@router.get("/drift-trend")
def drift_trend(limit: int = 100):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT timestamp, embedding_score, confidence_score, class_score, is_drift
        FROM drift_events
        ORDER BY timestamp DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    data = [
        {
            "timestamp": r[0],
            "embedding_score": r[1],
            "confidence_score": r[2],
            "class_score": r[3],
            "is_drift": bool(r[4]),
        }
        for r in reversed(rows)
    ]
    return {
        "thresholds": {"embedding": 0.55, "confidence": 0.55, "class": 0.55},
        "points": data,
    }


# ---------------- Review Queue ----------------
@router.get("/review-queue")
def review_queue():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.id, p.predicted_class, p.confidence, p.timestamp, p.quality_warnings
        FROM prediction_events p
        LEFT JOIN human_feedback h ON h.prediction_id = p.id
        WHERE h.prediction_id IS NULL
          AND (p.confidence < 0.6 OR COALESCE(p.quality_warnings, '[]') != '[]')
        ORDER BY p.confidence ASC, p.timestamp DESC
        LIMIT 50
    """)
    rows = cursor.fetchall()
    conn.close()

    def to_item(row):
        warnings = json.loads(row[4] or "[]")
        reasons = []
        if row[2] < 0.6:
            reasons.append("low confidence")
        if warnings:
            reasons.extend(warnings)
        return {
            "id": row[0],
            "predicted_class": row[1],
            "confidence": row[2],
            "timestamp": row[3],
            "quality_warnings": warnings,
            "review_reason": ", ".join(reasons),
            "suspicious_score": round((1 - min(max(row[2], 0), 1)) + (0.35 if warnings else 0), 3),
        }

    return [to_item(row) for row in rows]


@router.post("/review-queue/{prediction_id}/label")
def submit_label(prediction_id: int, payload: LabelRequest):
    true_label = payload.true_label.strip().lower()
    if true_label not in {"beverages", "snacks"}:
        raise HTTPException(status_code=400, detail="true_label must be 'beverages' or 'snacks'")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT predicted_class FROM prediction_events WHERE id = ?", (prediction_id,))
    prediction_row = cursor.fetchone()
    if prediction_row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="prediction_id not found")
    predicted_class = prediction_row[0]

    cursor.execute("SELECT id FROM human_feedback WHERE prediction_id = ?", (prediction_id,))
    existing = cursor.fetchone()
    if existing:
        cursor.execute(
            """
            UPDATE human_feedback
            SET true_label = ?, labeled_at = CURRENT_TIMESTAMP
            WHERE prediction_id = ?
            """,
            (true_label, prediction_id),
        )
    else:
        cursor.execute(
            """
            INSERT INTO human_feedback (prediction_id, true_label, labeled_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            """,
            (prediction_id, true_label),
        )

    conn.commit()
    conn.close()
    return {"status": "ok", "prediction_id": prediction_id, "true_label": true_label}


# ---------------- Alerts ----------------
@router.get("/alerts")
def get_alerts():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, alert_type, message, timestamp, resolved
        FROM alerts
        ORDER BY timestamp DESC
        LIMIT 100
    """)
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "alert_type": r[1],
            "message": r[2],
            "timestamp": r[3],
            "resolved": bool(r[4]),
        }
        for r in rows
    ]

@router.post("/alerts/{alert_id}/resolve")
def resolve_alert_endpoint(alert_id: int):
    resolve_alert(alert_id)
    return {"status": "resolved"}


# ---------------- Performance: metrics over time ----------------
@router.get("/performance/metrics-over-time")
def perf_over_time():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT strftime('%Y-%m-%d %H:00', prediction_events.timestamp) AS h,
               prediction_events.predicted_class,
               human_feedback.true_label
        FROM prediction_events
        JOIN human_feedback ON prediction_events.id = human_feedback.prediction_id
        ORDER BY prediction_events.timestamp ASC, prediction_events.id ASC
    """)
    rows = cursor.fetchall()
    conn.close()

    grouped = OrderedDict()
    for hour, pred, true in rows:
        grouped.setdefault(hour, []).append((pred, true))

    data = []
    classes = ["beverages", "snacks"]
    confusion = {c: {p: 0 for p in classes} for c in classes}
    total_labeled = 0
    total_correct = 0

    for hour, items in grouped.items():
        for pred, true in items:
            if pred not in classes or true not in classes:
                continue
            confusion[true][pred] += 1
            total_labeled += 1
            if pred == true:
                total_correct += 1

        accuracy = total_correct / total_labeled if total_labeled else 0
        f1_scores = []
        for cls in classes:
            tp = confusion[cls][cls]
            fp = sum(confusion[other][cls] for other in classes if other != cls)
            fn = sum(confusion[cls][other] for other in classes if other != cls)
            precision = tp / (tp + fp) if (tp + fp) else 0
            recall = tp / (tp + fn) if (tp + fn) else 0
            f1_scores.append(2 * precision * recall / (precision + recall) if (precision + recall) else 0)
        macro_f1 = sum(f1_scores) / len(f1_scores) if f1_scores else 0
        data.append({"hour": hour[5:16], "accuracy": round(accuracy, 3), "f1": round(macro_f1, 3), "labeled": total_labeled})

    return {"thresholds": {"accuracy": 0.8, "f1": 0.8}, "points": data}


# ---------------- Performance: summary ----------------
@router.get("/performance/summary")
def perf_summary():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT predicted_class, true_label
        FROM prediction_events
        JOIN human_feedback ON prediction_events.id = human_feedback.prediction_id
    """)
    rows = cursor.fetchall()

    total_preds = count_rows("SELECT COUNT(*) FROM prediction_events")
    conn.close()

    classes = ["beverages", "snacks"]
    cm = {c: {p: 0 for p in classes} for c in classes}
    for pred, true in rows:
        if true in classes and pred in classes:
            cm[true][pred] += 1

    labeled = len(rows)
    unlabeled = total_preds - labeled

    metrics = []
    for cls in classes:
        tp = cm[cls][cls]
        fp = sum(cm[other][cls] for other in classes if other != cls)
        fn = sum(cm[cls][other] for other in classes if other != cls)
        precision = tp / (tp + fp) if (tp + fp) else 0
        recall = tp / (tp + fn) if (tp + fn) else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0
        support = tp + fn
        metrics.append({
            "class": cls,
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "support": support,
        })

    return {
        "confusion_matrix": cm,
        "per_class": metrics,
        "coverage": {"labeled": labeled, "unlabeled": unlabeled},
        "warning": f"performance นี้คำนวณจาก {labeled} รายการที่มี label แล้ว\nยังมี {unlabeled} รายการที่รอ label อยู่\nตัวเลขนี้อาจไม่ตรงกับ performance จริงทั้งหมด"
    }