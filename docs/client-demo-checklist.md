# Vietnam Healthcare Claims Platform - Client Demo Checklist

**Final Status: MVP FROZEN — READY FOR CLIENT DEMONSTRATION**

## Demo Environment Setup

Run these commands from the project root (`/home/amar/Desktop/Vietnam`) to start the platform locally before the demo.

### 1. Database Initialization & Seeding
Reset the database and seed it with demo data (facilities, mapping rules, benchmark data):
```bash
cd backend
venv/bin/python scripts/reset_db.py
venv/bin/python scripts/seed_demo_data.py
```

### 2. Start Backend API
Run the backend application (default port 8000):
```bash
cd backend
venv/bin/uvicorn app.main:app --reload
```
- **API Documentation:** `http://localhost:8000/docs`

### 3. Start Frontend Dashboard
In a separate terminal, run the frontend (default port 5173):
```bash
cd frontend
npm run dev
```
- **Dashboard UI:** `http://localhost:5173`

### Demo Credentials
- **Admin Login:** `admin@example.com` / `adminpass`
- **Facility (Apollo F033) Login:** `facility1@example.com` / `facpass`

*(Note: Passwords are secure bcrypt hashes internally, but provided here in plaintext strictly for local demo usage).*

---

## Client Demo Flow

Follow these steps precisely to demonstrate the platform capabilities:

### 1. Admin Login
- Open `http://localhost:5173` and log in with admin credentials.
- **Talking Point:** Admins have centralized visibility over all healthcare network activity across all tenants.

### 2. Facility Login
- Log out, and log back in with Apollo F033 facility credentials.
- **Talking Point:** Strict tenant isolation guarantees facilities can only see their own transactions and settings.

### 3. Apollo F033 Dynamic Codes
- Navigate to the Transaction Submission or Configuration UI.
- **Talking Point:** Show that Apollo (F033) automatically receives only its specific HIS codes (e.g., `AP-CT-001`, `AP-LAB-010`). This demonstrates dynamic tenant-based provisioning over hardcoded UI dropdowns.

### 4. Normal Approved Transaction
- Submit a valid, standard claim through the frontend.
- **Talking Point:** Show the platform translating the local facility code to a unified standard code and instantly adjudicating the claim as `PASS`.

### 5. Price Anomaly / FWA Review
- Submit a claim with an unusually high price (e.g., a simple lab test billed for an exorbitant amount).
- **Talking Point:** The FWA engine will flag the transaction (`FWA-003 Price Anomaly`) and place it in a `REVIEW` state rather than automatically approving it.

### 6. Duplicate Transaction
- Resubmit the exact same claim reference from Step 4 or Step 5.
- **Talking Point:** The API gracefully rejects the duplicate (Idempotency) via FWA rule `FWA-001`. It returns the previously processed transaction state without duplicating database entries or triggering redundant TPA callbacks.

### 7. Transaction Detail & Processing Timeline
- Click into the details of any processed transaction.
- **Talking Point:** Walk through the complete lifecycle audit trail (Integration Events) showing: Submission -> Code Normalization -> FWA Benchmarking -> TPA Adjudication -> HIS Callback.

### 8. Facility Alert/History
- Show the notifications or alerts generated for the facility (e.g., when a claim requires review).
- **Talking Point:** Real-time visibility into claims status helps hospitals address rejected claims quickly.

### 9. Admin Visibility
- Log back in as Admin.
- **Talking Point:** Verify that the admin can view transactions spanning the entire network, seeing exactly how the FWA engine behaves across all tenants.

### 10. Integration Architecture Explanation
- **Talking Point:** Explain that the platform uses an adaptable `RESTAdapter` capable of ingesting diverse, heterogeneous HIS payloads and transforming them into a normalized standard. Emphasize that the "TPA/Core" module inside the app is a simulated boundary layer that represents how we would eventually route clean claims to actual core insurance systems.

---

## Known Demo-Only Limitations
- **TPA Simulation:** TPA adjudication is simulated internally. There is no live external TPA endpoint connection.
- **Monetary Precision:** Monetary values are currently implemented using standard `Float` fields. In a production environment, these will be migrated to exact precision `Numeric/Decimal` data types.
- **HIS Callback Environment:** Simulated callbacks point to `localhost:8000` (self). Live external hospital systems are required for real HTTP dispatching.
