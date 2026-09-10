# Vietnam Healthcare Claims Platform - Demo-Readiness Audit

## 1. Test Quality
**Status: PASS**
- **REST Adapter Test:** Strengthened. Now correctly tests the `/api/v1/integrations/rest/submit` route with correct headers and payload schema (`claim_reference`, `services`).
- **Duplicate Test:** Verified. The duplicate payload is rejected with `HTTP 201 Created` returning the idempotent response without triggering duplicate TPA callbacks or database events.
- **Tenant Isolation:** Verified. Facility users cannot view admin pages, and `404 Not Found` is correctly returned when accessing other facilities' transaction IDs.
- **Admin Visibility:** Verified.
- **Dynamic Codes:** Verified. Apollo `F033` receives precisely its seeded codes (`AP-CT-001`, `AP-LAB-010`).
- **Authentication:** Verified. No `DEMO-CODE` dummy strings are provisioned on signup.

## 2. FWA Coverage
**Status: PASS**
Added and verified test coverage for all 5 implemented FWA rules in `tests/test_qa_e2e.py`:
- `FWA-001 Duplicate Service`: Added `test_fwa_001_duplicate`. Triggered when the exact same code is submitted twice for the same patient on the same day.
- `FWA-002 Frequency Check`: Added `test_fwa_002_frequency`. 
- `FWA-003 Price Anomaly`: Covered by `test_qa_d_price_anomaly`.
- `FWA-004 Unusual Quantity`: Added `test_fwa_004_quantity`. 
- `FWA-005 Unusual Same-Day Combo`: Added `test_fwa_005_same_day_combo`.

## 3. Security Sanity Check
**Status: WARNING (Non-blocking for Demo)**
- **JWT Secret:** `app/config.py` defaults `JWT_SECRET_KEY` to `"CHANGE_ME_IN_PRODUCTION"`. This triggers an `InsecureKeyLengthWarning` because it is 30 bytes (RFC 7518 requires >= 32 bytes for SHA256). **Severity: LOW for Demo, HIGH for Production.**
- **Passwords:** `bcrypt` is correctly used via `passlib`. No plaintext passwords in DB or codebase.
- **Tenant Isolation:** Request payload `hospital_id` is safely overridden by the JWT token claims. Facilities are locked to their own data.

## 4. Demo Data Sanity
**Status: PASS**
- Apollo `F033` is cleanly seeded via `hospitals.csv` and `hospital_codes.csv`.
- No `DEMO-CODE` strings exist in the runtime provisioning path.

## 5. Alembic
**Status: PASS**
- `alembic current` matches `alembic heads` (fe81707939d6).
- `Base.metadata.create_all()` is fully removed from `main.py`.

## 6. Frontend Sanity
**Status: PASS**
- `npm run build` succeeds perfectly with Vite (built in 7.37s). No compilation errors or object placeholder bugs.

## 7. Money Precision
**Status: WARNING (Documented)**
> Monetary fields currently use Float and require Numeric/Decimal hardening before production financial processing.

## 8. Production Claim Boundary
**Status: PASS**
The platform is documented correctly as an MVP/demo decisioning and integration platform. It does not claim real-time universal HIS connectivity, live TPA integration, or production scale performance.

## 9. Final Test Run
```text
tests/test_qa_e2e.py::test_qa_a1_a2_a3_authentication PASSED
tests/test_qa_e2e.py::test_qa_b_dynamic_codes_apollo PASSED
tests/test_qa_e2e.py::test_qa_c_normal_transaction PASSED
tests/test_qa_e2e.py::test_qa_d_price_anomaly PASSED
tests/test_qa_e2e.py::test_qa_e_duplicate_transaction PASSED
tests/test_qa_e2e.py::test_qa_f_tenant_isolation PASSED
tests/test_qa_e2e.py::test_qa_g_admin_visibility_and_history PASSED
tests/test_qa_e2e.py::test_qa_h_rest_adapter PASSED
tests/test_qa_e2e.py::test_fwa_001_duplicate PASSED
tests/test_qa_e2e.py::test_fwa_002_frequency PASSED
tests/test_qa_e2e.py::test_fwa_004_quantity PASSED
tests/test_qa_e2e.py::test_fwa_005_same_day_combo PASSED

======================= 12 passed, 18 warnings in 13.76s =======================
```

## 10. Final Verdict

READY FOR CLIENT DEMO
