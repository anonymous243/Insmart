# READ-ONLY Forensic Diagnosis: Data Visibility Issue

## 1. FRONTEND API CONFIGURATION
- Both the Facility and Central Admin frontends are served by the exact same Vite application running on port 5173.
- Both use the identical API base URL prefix: `/api/v1` (proxied to `http://localhost:8000`).

## 2. DATABASE BACKEND CONFIGURATION
- There is only one backend instance (`uvicorn app.main:app`) and it connects to a single PostgreSQL database: `postgresql://claimuser:***@localhost:5432/claimsdb`.
- The database is properly populated. Inspecting the database confirms that `TXN-FAC-...` transactions from Facility 8 are successfully persisted in `claimsdb`.

## 3. FORENSIC CONCLUSION
**The root cause is an API Client Authentication mismatch on the Admin Dashboard.**

The Facility UI and Central Admin UI are using the **same database** and **same environment**. However, the Central Admin has an authentication delivery problem:

1. In `frontend/src/api/client.ts`, the Admin dashboard fetches data using `api.getTransactions()` and `api.getDashboardMetrics()`.
2. These functions are wired to use a simple `get()` wrapper which relies on a raw `fetch()` **without** an `Authorization` header.
3. During the QA phase, we correctly enforced Admin authorization on the backend (`list_transactions` now uses `Depends(get_current_admin_user)`).
4. Because the frontend Admin UI does not send its JWT token for these endpoints, the backend immediately rejects the requests with a `401 Unauthorized` (confirmed via backend logs).
5. The `Overview.tsx` frontend page uses `Promise.all([api.getDashboardMetrics(), api.getTransactions()])` which lacks a `.catch()` block for the `401` errors, swallowing the failure and leaving the local state empty. 

Thus, the submitted data is not gone; it is fully present in the database, but the Admin UI is failing to authenticate its read requests.
