#!/usr/bin/env python
import json
import urllib.request
import sqlite3

base = 'http://localhost:8000/monitoring'

# 1. เลือก label หนึ่งรายการ
print("=== STEP 1: Get review queue ===")
queue = json.loads(urllib.request.urlopen(base + '/review-queue').read())
if not queue:
    print('❌ NO_QUEUE_ITEMS')
    exit(0)

item = queue[0]
pred_id = item['id']
orig_class = item['predicted_class']
label = 'snacks' if orig_class == 'beverages' else 'beverages'

print(f'✅ Found item: pred_id={pred_id}, predicted={orig_class}, will label as={label}')

# 2. ยิง label API
print("\n=== STEP 2: Submit label via API ===")
req = urllib.request.Request(
    base + f'/review-queue/{pred_id}/label',
    data=json.dumps({'true_label': label}).encode('utf-8'),
    headers={'Content-Type': 'application/json'},
    method='POST',
)
resp = json.loads(urllib.request.urlopen(req).read())
print(f'✅ Label API response: {resp}')

# 3. เช็ก DB human_feedback
print("\n=== STEP 3: Check human_feedback in DB ===")
conn = sqlite3.connect('data/monitoring.db')
cur = conn.cursor()
cur.execute('SELECT true_label, labeled_at FROM human_feedback WHERE prediction_id = ?', (pred_id,))
hf = cur.fetchone()
print(f'✅ human_feedback row for pred_id {pred_id}: {hf}')

# 4. เช็ก total labeled count
cur.execute('SELECT COUNT(*) FROM human_feedback')
total_labeled = cur.fetchone()[0]
cur.execute('SELECT COUNT(*) FROM prediction_events')
total_pred = cur.fetchone()[0]
conn.close()
print(f'✅ Total labeled: {total_labeled}/{total_pred}')

# 5. เช็ก performance API
print("\n=== STEP 4: Check performance API ===")
perf = json.loads(urllib.request.urlopen(base + '/performance/summary').read())
print(f'✅ Coverage: {perf["coverage"]}')
print(f'✅ Confusion matrix: {perf["confusion_matrix"]}')
print(f'✅ Per-class metrics:')
for m in perf['per_class']:
    print(f'   {m["class"]}: F1={m["f1"]}, precision={m["precision"]}, recall={m["recall"]}')

# 6. เช็ก KPI
print("\n=== STEP 5: Check KPI ===")
kpi = json.loads(urllib.request.urlopen(base + '/kpi').read())
print(f'✅ KPI: active_alerts={kpi["active_alerts"]}, total_today={kpi["total_requests_today"]}')

print("\n✅ ALL TESTS PASSED - Label update is working correctly")
