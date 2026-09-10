# Facility Integration Upgrade Plan

## 1. Existing Architecture & Objective
The Vietnam Claims Platform currently functions as a generic "HIS transaction simulator". The objective is to evolve it into a robust "Vietnam Healthcare Claims Integration & Decisioning Platform". The core idea is that hospitals have heterogeneous HIS systems (REST, Vendor APIs, SFTP, CSV) and do not natively speak the central canonical format. 

The platform will introduce an **Integration Adapter Layer** that standardizes inbound data into a **Canonical Transaction Model** before applying code normalization, FWA, benchmarking, and core adjudication. Finally, it will standardize outward communication (e.g., webhook callbacks) for decisions.

## 2. Files to Modify

### Backend
- **`app/models/__init__.py`**: Add `UNIQUE(hospital_id, transaction_id)` to `Transaction`. Extend `Hospital` to track `integration_type` and `response_endpoint`.
- **`app/schemas/__init__.py`**: Update payloads for dynamic adapters.
- **`app/api/v1/routes_transactions.py`**: Fix unauthenticated spoofing. Protect admin routes.
- **`app/api/v1/routes_hospitals.py`, `routes_auth.py`, `routes_codes.py`**: Apply strict Admin vs Facility RBAC protection.
- **`app/api/v1/routes_facility.py`**: Remove hardcoded code fallbacks; ensure `get_facility_codes` only returns mapped database codes. Expand `get_facility_alerts` and `get_facility_history` to support the required details.
- **`app/services/transaction_orchestrator.py`**: Ensure rejection/review generates callbacks. Improve idempotency check with DB transaction locks.
- **`app/services/his_callback_service.py`**: Expand to handle structured decision payloads and log specific integration events.
- **`app/services/code_mapping_service.py`**: Remove previous demo hacks; enforce strict dynamic mapping.

### Frontend
- **`src/pages/facility/NewSubmission.tsx`**: Remove hardcoded codes, fetch dynamically via `/api/v1/facility/codes`. Use synthetic patient references.
- **`src/pages/facility/Dashboard.tsx`**: Update layout to display facility stats and integration status.
- **`src/pages/facility/History.tsx`**: Ensure isolated history view.
- **`src/pages/facility/Account.tsx`**: Show Integration Type and Status.
- **`src/components/AdminLayout.tsx` & `FacilityLayout.tsx`**: Clean up navigation terminology ("HIS Transaction Simulation" for admin, "Facility Submission" for portal).

## 3. New Files
- **`app/services/integrations/base_adapter.py`**: Abstract base class for HIS adapters.
- **`app/services/integrations/rest_adapter.py`**: Concrete implementation for JSON/REST integrations.
- **`app/services/integrations/file_adapter.py`**: Stubs for CSV/File-based exchange.
- **`app/services/integrations/adapter_registry.py`**: Factory to instantiate adapters based on facility config.
- **`tests/test_facility_integration.py`**: Comprehensive pytest suite covering auth, duplicate submissions, Rejection endpoints, FWA rules, and tenant isolation.

## 4. Database Changes (via Alembic)
1. **Migration 1**: Add `UNIQUE CONSTRAINT (hospital_id, transaction_id)` to `transactions` table to enforce safe idempotent submissions.
2. **Migration 2**: Add `integration_type` (e.g. `REST_API`, `SFTP`) and `response_endpoint` to `hospitals` table.

## 5. API Changes
- **POST `/api/v1/facility/transactions`**: The new primary endpoint for facility portal submissions (uses JWT strictly).
- **POST `/api/v1/integrations/rest/submit`**: The adapter endpoint for REST API integration simulating real HIS pushes.
- **GET `/api/v1/facility/alerts`**: Upgraded to include transaction adjudication status.
- **RBAC**: All `/admin/*` routes strictly protected.

## 6. Frontend Changes
- **Routing**: Ensure isolated protected routes for Facility vs Admin.
- **Dynamic Codes**: `NewSubmission.tsx` completely driven by DB mappings.
- **Terminology**: Replace "real-time hospital data" with realistic terminology like "Process data as it becomes available".

## 7. Migration Strategy
- Run Alembic generation `alembic revision --autogenerate -m "integration updates"`.
- Run `alembic upgrade head`.
- Inject a new facility (e.g., Apollo Hospital F033) via seed script with custom local codes (`AP-CT-001`, `AP-LAB-010`) to test dynamic code generation.

## 8. Test Strategy
- **Backend**: Implement pytest suite to collect and pass ≥ 20 tests covering idempotency, JWT tenant isolation, FWA 001-005, dynamic codes, and rejection workflows.
- **Frontend**: Run `npm run build` to ensure no TS errors.
- **E2E**: Execute Scenarios A (New Facility), B (Price Anomaly), C (Duplicate), D (Tenant Isolation), and E (Dynamic Codes) manually in the UI as final validation.

## 9. Open Questions for User
- The current implementation has a mock authentication setup using plaintext passwords (requested in a prior task due to bcrypt issues). Should I re-introduce a lightweight hash (like SHA256) for this MVP to make it slightly more secure, or keep plaintext for the demo?
- Is there a preferred URL structure for the mock TPA endpoint, or should it remain fully internal to the orchestrator?
