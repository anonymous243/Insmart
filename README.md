# Healthcare Claims Processing Platform

A 2-day professional proof-of-concept demonstrating a centralized healthcare claims integration, normalization, FWA decisioning, and TPA routing platform.

## Core Business Concept

Hospitals continue using their **existing HIS systems**. Our platform is the centralized integration boundary:

```
Hospital HIS  →  Central API Hub  →  Code Normalization  →  Benchmarking  →  FWA  →  Mock TPA  →  HIS Callback
```

- ✅ Hospital does NOT log into a portal
- ✅ Hospital does NOT integrate separately with every TPA  
- ✅ Hospital does NOT enter data twice
- ✅ Hospital continues using its existing HIS

---

## Quick Start

### 1. Start PostgreSQL

The platform requires PostgreSQL. An existing container is used, or start one:

```bash
docker compose up -d
```

### 2. Start Backend

```bash
cd backend
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The backend auto-creates tables and seeds data on first startup.

### 3. Start Frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**

### 4. API Documentation

Open **http://localhost:8000/docs**

---

## Demo Scenarios

### Scenario 1 — APPROVED (Within Benchmark)
```bash
curl -X POST http://localhost:8000/api/v1/transactions \
  -H "Content-Type: application/json" \
  -d '{
    "hospital_id": "H001",
    "transaction_id": "TXN-DEMO-001",
    "patient_reference": "P90001",
    "items": [
      {"hospital_code": "CARD001", "description": "Cardiology Consultation", "quantity": 1, "unit_price": 700},
      {"hospital_code": "XR001", "description": "Chest X-Ray", "quantity": 1, "unit_price": 480}
    ]
  }'
```
**Expected**: CARD001 → CONS-CARD, XR001 → XR-CHEST. Both within benchmark. FWA PASS. TPA **APPROVED**.

---

### Scenario 2 — REVIEW (Price Anomaly)
```bash
curl -X POST http://localhost:8000/api/v1/transactions \
  -H "Content-Type: application/json" \
  -d '{
    "hospital_id": "H002",
    "transaction_id": "TXN-DEMO-002",
    "patient_reference": "P90002",
    "items": [
      {"hospital_code": "CC-102", "description": "Cardiac Consultation", "quantity": 1, "unit_price": 1100}
    ]
  }'
```
**Expected**: CC-102 → CONS-CARD. Benchmark RM 750, Max RM 900. Submitted RM 1100. FWA **PRICE_FLAG**. TPA **REVIEW**.

---

### Scenario 3 — REJECTED (Duplicate Service)
Submit Scenario 1 again with the **same patient reference** and **same hospital** on the same day:
```bash
curl -X POST http://localhost:8000/api/v1/transactions \
  -H "Content-Type: application/json" \
  -d '{
    "hospital_id": "H001",
    "transaction_id": "TXN-DEMO-003",
    "patient_reference": "P90001",
    "items": [
      {"hospital_code": "CARD001", "description": "Cardiology Consultation", "quantity": 1, "unit_price": 700}
    ]
  }'
```
**Expected**: FWA-001 **DUPLICATE SERVICE** flagged. TPA **REJECTED**.

---

## Architecture

```
backend/
  app/
    api/v1/
      routes_transactions.py  ← POST /api/v1/transactions (HIS entry point)
      routes_tpa.py           ← POST /api/v1/tpa/adjudicate (Mock TPA)
      routes_hospitals.py     ← POST /api/v1/hospitals/{id}/adjudication (HIS callback)
      routes_codes.py         ← GET /api/v1/codes/mappings, /dashboard/metrics
    services/
      transaction_orchestrator.py  ← Heart of the platform (process_transaction)
      code_mapping_service.py      ← Hospital code → Common code resolution
      benchmark_service.py         ← Price benchmark evaluation
      fwa_engine.py                ← 3 FWA rules (Duplicate, Frequency, Price)
      tpa_client.py                ← HTTP client calling mock TPA
      his_callback_service.py      ← HTTP client calling simulated HIS
    models/__init__.py       ← All SQLAlchemy models
    schemas/__init__.py      ← All Pydantic schemas
    seed/seed_data.py        ← 3 hospitals, 9 codes, 9 mappings, 3 benchmarks

frontend/
  src/
    api/client.ts            ← Typed API client
    pages/
      Overview.tsx           ← Live metrics dashboard
      CodeMaster.tsx         ← Hospital code normalization view
      Transactions.tsx       ← Transaction list + detail + demo buttons
      FWABenchmark.tsx       ← FWA rules + price analysis
      Adjudication.tsx       ← TPA decisions + HIS delivery status
    components/
      StatusBadge.tsx        ← Color-coded status badges
      ProcessingTimeline.tsx ← Integration event timeline
```

## Benchmark Reference

| Common Code | Description | Benchmark | Variance | Max |
|---|---|---|---|---|
| CONS-CARD | Cardiology Consultation | RM 750 | 20% | RM 900 |
| LAB-CBC | Complete Blood Count | RM 300 | 15% | RM 345 |
| XR-CHEST | Chest X-Ray | RM 500 | 20% | RM 600 |

## FWA Rules

| Rule | Name | Trigger | Action |
|---|---|---|---|
| FWA-001 | Duplicate Service | Same patient + hospital + code + day | FWA_FLAG → REJECTED |
| FWA-002 | Frequency Check | >3 same code/patient in 7 days | FWA_REVIEW |
| FWA-003 | Price Anomaly | Submitted > benchmark maximum | PRICE_FLAG → REVIEW |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | /api/v1/transactions | HIS submits claim |
| GET | /api/v1/transactions | List all transactions |
| GET | /api/v1/transactions/{id} | Full transaction detail + timeline |
| POST | /api/v1/tpa/adjudicate | Mock TPA adjudication |
| POST | /api/v1/hospitals/{id}/adjudication | Simulated HIS callback |
| GET | /api/v1/hospitals | List connected hospitals |
| GET | /api/v1/codes/mappings | Code master view |
| GET | /api/v1/dashboard/metrics | Live dashboard metrics |
| GET | /health | Health check |
| GET | /docs | OpenAPI documentation |
