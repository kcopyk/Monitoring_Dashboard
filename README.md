# Monitoring Dashboard (SEforML)

โปรเจกต์นี้เป็นระบบ Monitoring สำหรับงาน ML ประกอบด้วย
- Backend: FastAPI + SQLite
- Frontend: React + Vite
- ข้อมูลตัวอย่าง: script สำหรับ seed mock data

## 1) Prerequisites

- Python 3.10+ (แนะนำ 3.11)
- Node.js 18+ และ npm
- Git

ตรวจเวอร์ชัน:

```bash
python --version
node --version
npm --version
git --version
```

## 2) ติดตั้งและรัน Backend (FastAPI)

รันจากโฟลเดอร์หลักของโปรเจกต์:

```bash
cd monitoring-dashboard
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### สร้าง/เติมข้อมูล mock ลงฐานข้อมูล

```bash
python scripts/seed_mock_data.py --reset
```

ตัวอย่างปรับปริมาณข้อมูล:

```bash
python scripts/seed_mock_data.py --hours 168 --per-hour 12 --label-rate 0.4 --reset --seed 42
```

### รัน API

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

เมื่อรันสำเร็จ:
- API base: http://localhost:8000
- Health endpoint: http://localhost:8000/
- Monitoring endpoints: http://localhost:8000/monitoring
- DB web preview: http://localhost:8000/monitoring/db-web

## 3) ติดตั้งและรัน Frontend (React + Vite)

เปิด terminal ใหม่ แล้วรัน:

```bash
cd monitoring-dashboard/frontend
npm install
npm run dev
```

Frontend จะรันที่:
- http://localhost:5173

โดยค่าเริ่มต้น frontend เรียก backend จาก `http://localhost:8000` ผ่านตัวแปร `VITE_API_URL` ในไฟล์ `frontend/.env`.

## 4) ทดสอบ flow อย่างเร็ว

หลัง backend ทำงานแล้ว สามารถเรียกจำลอง prediction ได้:

```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"predicted_class":"snacks","confidence":0.92,"latency_ms":120}'
```

ทดสอบการอัปเดต label และ performance metrics:

```bash
python test_label_update.py
```

## 5) โครงสร้างโปรเจกต์แบบย่อ

```text
monitoring-dashboard/
├── app/                      # FastAPI app
├── src/monitoring/           # monitoring logic (store, orchestrator, quality)
├── scripts/                  # scripts เช่น seed_mock_data.py
├── data/                     # SQLite DB (monitoring.db)
├── frontend/                 # React + Vite dashboard
├── requirements.txt
└── test_label_update.py
```

## 6) Push ขึ้น GitHub Repo ใหม่

### 6.1 สร้าง repo ใหม่บน GitHub

- เข้า GitHub แล้วสร้าง repository ใหม่ (ยังไม่ต้อง add README/.gitignore จากหน้าเว็บ)
- คัดลอก URL ของ repo เช่น `https://github.com/<username>/<repo>.git`

### 6.2 push โค้ดจากเครื่องขึ้น repo ใหม่

รันจากโฟลเดอร์ `monitoring-dashboard`:

```bash
git init
git add .
git commit -m "Initial commit: monitoring dashboard"
git branch -M main
git remote add origin https://github.com/<username>/<repo>.git
git push -u origin main
```

ถ้าเคยตั้ง remote `origin` ไว้แล้ว:

```bash
git remote set-url origin https://github.com/<username>/<repo>.git
git push -u origin main
```

## 7) หมายเหตุ

- ถ้าใช้งาน zsh/macOS ให้ใช้ `source venv/bin/activate`
- ถ้าใช้ Windows ให้ใช้ `venv\\Scripts\\activate`
- หากพอร์ตชนกัน ให้เปลี่ยนพอร์ตตอนรัน `uvicorn` หรือ `npm run dev`
