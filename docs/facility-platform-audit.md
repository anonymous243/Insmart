# Facility Platform Audit

## Current Architecture
The current platform is a monolithic Python/FastAPI backend serving a React/Vite frontend. It implements a complete transaction processing pipeline simulating a Central API Hub for healthcare claims. The frontend is largely a demonstration dashboard that triggers hardcoded deterministic demo scenarios. 

## Existing Transaction Flow
1. **Receive**: `POST /api/v1/transactions`
2. **Validate**: Check hospital existence and valid codes.
3. **Normalize**: Map local facility codes (`HospitalCode`) to common terminology (`CommonCode`).
4. **Benchmark**: Check if submitted price is within allowed variance of `PriceBenchmark`.
5. **FWA**: FWA Engine evaluates rules (e.g. Duplicates, Price Anomalies).
6. **TPA/Adjudication**: Mock TPA Client adjudicates the claim.
7. **HIS Callback**: Integration event logged simulating HIS response delivery.
8. **Result**: Status is returned and integration events are persisted.

## Existing Authentication State
**None.** The system currently has no authentication or authorization mechanism. Hospital IDs are passed in plaintext via the API request payload, which the backend trusts blindly.

## Existing Database Models
- `TerminologySystem`
- `Patient` (synthetic demo only)
- `Hospital`
- `HospitalCode`
- `CommonCode`
- `CodeMapping`
- `PriceBenchmark`
- `FWARule`
- `Transaction`
- `TransactionItem`
- `FWAResult`
- `Adjudication`
- `IntegrationEvent`

## Existing Endpoints
- `POST /api/v1/transactions`
- `GET /api/v1/transactions`
- `GET /api/v1/transactions/{id}`
- `GET /api/v1/hospitals`
- `GET /api/v1/codes/mappings`
- `POST /api/v1/demo/reset`
- `GET /api/v1/audit/logs`

## Existing Business Logic
- The `transaction_orchestrator.py` handles the full pipeline and is the single source of truth.
- Duplicate detection is currently based only on a basic idempotency check on `transaction_id`.

## Existing Demo Functionality
- Deterministic demo scenarios located in `frontend/src/pages/Transactions.tsx` that submit pre-defined JSON payloads.
- `seed_data.py` populates the DB with `data/vietnam` CSVs on startup if the DB is empty.

## Files that must NOT be unnecessarily rewritten
- `app/services/transaction_orchestrator.py` (The core pipeline must be wrapped, not replaced)
- `app/services/benchmark_service.py`
- `app/services/fwa_engine.py`
- `app/services/tpa_client.py`
- `app/services/his_callback_service.py`
- Existing central operations React components.

## Proposed Extension Points
- **Authentication**: Add JWT-based Auth with `User` and `FacilityUser` models.
- **Tenancy**: Add dependency injection to `api` routes to resolve `current_user` and enforce facility scope.
- **Frontend**: Introduce React Router to separate `/facility/*` from `/admin/*` and add `/login` + `/signup` views.
- **Transaction Route**: Modify `POST /api/v1/transactions` to resolve the `hospital_id` from the authenticated context instead of the JSON payload.
- **Idempotency/Duplicates**: Enhance idempotency check in `process_transaction` to prevent race conditions and ensure transactions are scoped by `hospital_id`.

## Risks/Conflicts
- Altering the `TransactionIn` schema might break the existing deterministic demos if they pass `hospital_id` explicitly. The deterministic demos will either need to send an auth token or bypass auth for demo mode.
- Modifying `Hospital` model might conflict with existing seed data if not migrated properly.
