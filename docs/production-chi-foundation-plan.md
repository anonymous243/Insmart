# Production CHI Foundation Plan

## Phase 0: Forensic Inspection
**Status**: COMPLETED

We have successfully inspected the existing MVP architecture. It utilizes a `Transaction` domain alongside `Hospital`, `HospitalCode`, `CommonCode`, and `CodeMapping`.
Alembic is set up correctly in `backend/alembic`. The frontend relies on React Context (`AuthContext.tsx`) for authorization via JWT stored in `localStorage`. Tests heavily use the `seeded_client` with shared sqlite in-memory DB instances per test. 
The system does not currently have `Claim`, `Member`, or `Policy` models.

## Phase 1: Fix and Verify Authentication
**Status**: COMPLETED

Browser authentication and API client delivery issues are resolved.
- Backend Admin endpoints and transactions are correctly secured behind `ADMIN` role checks.
- API requests via `fetchWithAuth()` successfully transport `Bearer <token>`.
- React `AuthContext` reliably loads `user` and `token` from `localStorage` without race conditions.
- Facility submissions (`POST /demo/submit`) validate the active facility mappings successfully and map to `TEST-AUTH` correctly.
- Admin dashboard queries correctly return cross-facility aggregated data and transaction visibility using a dedicated admin endpoint without Tenant Isolation constraints.

## Phase 2: Canonical Claim Model
**Goal**: Evolve the existing `Transaction` model into a more robust `Claim` model without deleting `Transaction` abruptly.
- Create `Claim` and `ClaimItem` models with properties: Facility, Patient, Encounter, Member, Policy, Currency, etc.
- Support `Transaction` -> `Claim` compatibility strategy.
- Add `Patient` entity for structured reference.
- Add `Encounter` entity.

## Phase 3: Commercial Member & Policy
**Goal**: Introduce a basic Commercial Insurance Domain.
- Create `Member` model linking to a specific `CommercialPolicy`.
- Create `CommercialPolicy` model with effective dates, limits, and rules.
- Create `CoverageRule` referencing the `CommonCode` to define coverage rules and deductibles.

## Phase 4: Eligibility
**Goal**: Check member CHI eligibility before claim processing.
- Create `EligibilityCheck` record to trace API requests.
- Integrate into the claim flow to set states: ELIGIBLE, INELIGIBLE, UNKNOWN.
- Create a mock external eligibility boundary for MVP testing.

## Phase 5: Coordination of Benefits (COB)
**Goal**: Support primary payer context (SHI) prior to CHI payment.
- Capture SHI paid/deducted amounts on the `Claim`.
- Add `COBRecord` entity for traceability.
- Route remaining balance to CHI benefit rules.

## Phase 6: CHI Benefit Calculation
**Goal**: Deterministic server-side financial calculation engine.
- Calculate Deductible, Copay, Coinsurance, and Out-of-pocket maximums based on `CoverageRule` and `COBRecord`.
- Record these components on `ClaimItem` or a `FinancialDecision` table.
- Calculate precise Payer vs Patient responsibility.

## Phase 7: Money Precision
**Goal**: Replace Float with `NUMERIC(15, 2)` / `Decimal` for all financial tables (`Transaction`, `Claim`, `PriceBenchmark`).
- Create an Alembic migration converting `Float` to `Numeric`.
- Add backend invariants ensuring `payer_responsibility + patient_responsibility + non_covered_amount == applicable claim amount`.

## Phase 8: Claim State Machine
**Goal**: Protect status transitions.
- Enforce valid state transitions (e.g., `DRAFT` -> `SUBMITTED` -> `PENDING_ELIGIBILITY` -> `ADJUDICATING` -> `APPROVED`).
- Log state changes with correlation IDs for auditability.

## Phase 9: Authorization
**Goal**: Pre-authorization capabilities for specific services.
- Define a flag on `CommonCode` or `CoverageRule` specifying `authorization_required`.
- Model authorization status: APPROVED, REJECTED, PENDING.

## Phase 10: Existing FWA + Benchmarking
**Goal**: Bring existing 5 FWA rules into the CHI pipeline.
- Evaluate FWA rules post-COB and Benchmarking.
- Produce FWA findings with severity and rules version tracking.

## Phase 11: CHI Adjudication
**Goal**: Evolve the existing TPA mock into a deterministic CHI adjudication boundary.
- Process all claim data inputs (COB, Eligibility, Auth, FWA, Benchmarks).
- Return standard deterministic results including `UNKNOWN`.
- Persist the adjudication request and result cleanly.

## Phase 12: Manual Review
**Goal**: Centralized Review Queue for Admin.
- Build UI for Admin to view pending/pended claims.
- Enable `APPROVE`, `PARTIALLY_APPROVE`, `REJECT`, and `PEND` actions.
- Provide full context (COB, Eligibility, FWA).

## Phase 13: Claim Resubmission / Amendment
**Goal**: Versioned claim modifications.
- Create `ClaimVersion` to trace changes if a hospital corrects a claim after initial submission.
- Ensure decisions are tracked per version.

## Phase 14: Central Admin — All Hospitals
**Goal**: Operational Network Dashboard.
- Upgrade Admin UI with aggregated charts and performance metrics.
- Add approval rates, FWA rates, integration health metrics.

## Phase 15: Facility Experience
**Goal**: Secure, tenant-isolated dashboard.
- Display facility-specific submissions, alerts, and configured mappings.
- Restrict visibility strictly to their own data.

## Phase 16: Integration Architecture
**Goal**: Scalable Adapters for canonical claim generation.
- Keep the REST adapter.
- Scaffold CSV/SFTP boundaries mapping to the canonical `Claim` structure.

## Phase 17 & 18 & 19 & 20: Durable Processing, Idempotency, Audit, Security
**Goal**: Enterprise robustness.
- Use explicit SQL conflicts/integrity constraints for idempotency.
- Maintain comprehensive integration and audit event ledgers.
- Keep JWT auth secure, implement robust RBAC.

## Phase 21 & 22: Testing & Migrations
**Goal**: Safe evolution.
- Alembic will handle all schema updates (no `drop_all` / `create_all`).
- Tests will be expanded to assert invariant checking and business flows.

## 10,000-Hospital Scale Strategy

### A. CURRENT ARCHITECTURE ASSESSMENT
- **Tenant Model**: Facility users are authenticated via JWT, strictly mapping to a single `hospital_id`. `AdminUser` has global visibility.
- **Hospital/Canonical Claim Model**: `Transaction` creates a strict 1:1 canonical `Claim`. Unresolved insurance creates a `Claim` in `PENDING_ELIGIBILITY`.
- **Query Patterns**:
  - Central Admin: `GET /api/v1/transactions` pulls latest 200 via `created_at desc`. Lacks pagination.
  - Facility: `GET /api/v1/facility/history` pulls latest 200 via `created_at desc`. Lacks pagination.
- **Indexes**: Basic B-Tree indexes exist (`ix_claims_id`, `ix_claims_hospital_status`, `ix_claims_hospital_created`), but are not optimized for keyset pagination.
- **Synchronous vs Asynchronous**: The entire `TransactionOrchestrator` runs synchronously in the FastAPI event loop (Validation -> FWA -> Adjudication -> Callback).
- **Idempotency**: Unique database constraint on `Claim.transaction_id` handles race conditions; FastAPI returns the existing transaction gracefully.

### B. SCALE ASSUMPTIONS (Engineering Load-Test Assumptions)
*Note: The following are engineering load-test assumptions pending confirmation from the client/business. They are NOT confirmed client requirements.*
- **Hospitals**: 10,000 active facilities.
- **Claims/Day/Hospital**: ~200 (Baseline), ~1,000 (High).
- **Total Claims/Day**: 2,000,000 (Baseline) to 10,000,000 (High).
- **Average Claims/Second**: ~23 claims/sec (at 2M/day) to ~116 claims/sec (at 10M/day).
- **Peak Claims/Second**: 500 TPS (This is retained strictly as a stress-test target scenario, not a confirmed production requirement).
- **Concurrent Users**: ~500 Admin users, ~15,000 Facility users.
- **Retention**: Active database retention of 13 months before archival.
- **Storage Growth**: ~5-10 GB/day.

### C. IDENTIFIED BOTTLENECKS
1. **N+1 Queries**: `routes_facility.py:get_facility_codes` performs a `db.query(CodeMapping).first()` inside a loop over local hospital codes.
2. **Unbounded/LIMIT Pagination**: Admin and Facility lists use hardcoded `.limit(200)` without cursor/offset capabilities, making deep history retrieval impossible.
3. **Synchronous Callbacks**: `HISCallbackService` blocks the main request thread while HTTP posting to the HIS, exposing the API to external timeout cascades.
4. **Database Connection Pool**: FastAPI running multiple workers with the default SQLAlchemy pool size (5) will quickly exhaust connections or queue under load.

### D. REQUIRED CHANGES
1. **Query/Index Hardening**:
   - Refactor `get_facility_codes` to use a single `IN` clause or SQL `JOIN` instead of N+1.
   - Implement deterministic keyset/cursor pagination for high-volume timelines (`/history`, `/transactions`). The query must use `ORDER BY created_at DESC, id DESC`. The cursor must contain both `(created_at, id)` to correctly continue and avoid duplicates or skipped records when timestamps are identical.
2. **Integration Durability and State Semantics**:
   - Before external TPA calls are moved into durable asynchronous processing, define durable attempt/state semantics for external requests.
   - States should explicitly distinguish: `NOT_DISPATCHED`, `DISPATCHED`, `RESPONSE_RECEIVED`, `UNKNOWN_OUTCOME`, and `FAILED`.
   - *Rule*: Do not retry an external request merely because the HTTP client timed out without determining whether the request may already have been dispatched.
3. **Connection Pool Tuning**:
   - Connection pool sizing must be derived from: PostgreSQL `max_connections`, number of application instances, workers per instance, expected concurrent database operations, Admin query concurrency, and background worker concurrency when introduced.
   - Initial pool settings should be measured and load-tested. PgBouncer is a potential later optimization, not a current requirement.
4. **Failure Isolation**: Implement strict timeouts and circuit breakers on HIS and TPA HTTP adapters.

### E. ARCHITECTURAL DECISIONS (DO NOT OVERENGINEER)
- **Modular Monolith**: Keep the modular monolith unless measured load, operational isolation, or deployment requirements demonstrate a concrete need to extract a component. Do not introduce microservices merely because the target contains 10,000 hospitals.
- **Database Partitioning**: Evaluate PostgreSQL partitioning when table/index size, query latency, vacuum/autovacuum behavior, retention/archival operations, or measured maintenance cost justify it. Row count is one input, not the sole trigger.
- **Caching**: Read workloads are highly cacheable in-process. Do not introduce Redis or distributed caching yet.

### F. LOAD-TEST PLAN
- **Scenarios**: 1,000, 5,000, and 10,000 simulated hospital profiles.
- **Acceptance Metrics**:
  - Unexpected HTTP 5xx rate
  - Request timeout rate
  - p50/p95/p99 latency
  - Throughput
  - Database errors
  - Duplicate/lost claim detection
  - Idempotency correctness
  - Data integrity
  - Controlled handling of dependency failures
  *(Note: Business outcomes such as rejected claims, `PENDING_ELIGIBILITY`, FWA flags, or duplicate/idempotent submissions must NOT be counted as infrastructure failures).*

### G. RECOMMENDED ROADMAP
- **C0 — Architecture/design** *(COMPLETE)*
- **C1 — Query/index/database access hardening** *(COMPLETE)*
- **C2 — Durable processing and external-attempt state model** *(REQUIRED NOW)*
- **C3 — Async worker boundary** *(CONDITIONAL)*
- **C4 — Integration durability/retries/failure isolation** *(CONDITIONAL)*
- **C5 — Observability** *(CONDITIONAL)*
- **C6 — Synthetic 1k/5k/10k hospital scale dataset** *(REQUIRED FOR TESTING)*
- **C7 — Load testing and bottleneck measurement** *(REQUIRED FOR TESTING)*
- **C8 — Production infrastructure scaling based on measured results** *(CONDITIONAL)*

Architecture target: approximately 10,000 hospitals. This target has NOT yet been performance validated. Claims/day, peak TPS, concurrent users, retention, and storage figures are engineering load-test assumptions pending confirmation and measurement.

### H. C1 IMPLEMENTATION REPORT (Query / Index / Database Access Hardening)
**Status**: COMPLETED

#### 1. API Contract & Cursor Semantics
- Paginated endpoints (`GET /api/v1/facility/history`, `GET /api/v1/transactions`) now return `{"items": [...], "next_cursor": "...", "has_more": true}`.
- Pagination limits: default `50`, max `200`. Strict server-side validation returns `422` for `< 1` or `> 200`.
- Keyset ordering is strictly `ORDER BY created_at DESC, id DESC`.
- The cursor is an opaque base64-encoded JSON array containing `[created_at_iso, id]`.
- Continuation queries use deterministic keyset semantics: `created_at < cursor_created_at OR (created_at = cursor_created_at AND id < cursor_id)`.
- Tenant isolation (hospital_id) remains independently enforced via JWT. The cursor does not carry authorization scope.

#### 2. N+1 Resolution
- `routes_facility.py:get_facility_codes` was refactored from performing an N+1 `db.query(CodeMapping)` loop to a set-based `outerjoin(CodeMapping)`.
- It preserves existing semantics and tenant isolation.

#### 3. Indexes & Query Plan Observations
- **Added**: A composite index `idx_transactions_hospital_created_id` on `(hospital_id, created_at DESC, id DESC)` was introduced via Alembic migration `7253ecbff076_phase_c1_keyset_indexes.py` to optimize facility history pagination.
- **Added**: A composite index `idx_transactions_created_id` on `(created_at DESC, id DESC)` was introduced to optimize admin-wide pagination.
- **Intentionally Not Added**: We avoided adding excessive indexes for unstructured JSONB filtering yet until query patterns for specific JSON fields are confirmed.
- **Query Plan**: Composite indexes required for the documented keyset query patterns are present and schema-verified. Current development data is too small to establish meaningful planner/index performance characteristics. Index utilization and performance under realistic data volumes are deferred to C6/C7 synthetic scale and load testing.

#### 4. Tests & Build Verification
- All 48 backend tests (`pytest tests/`) pass, including new assertions for N+1 elimination and the keyset pagination API contract.
- The frontend build (`npm run build`) completed successfully.
- Alembic was verified to have exactly one head (`7253ecbff076`) applied correctly (`alembic upgrade head`).

#### 5. Remaining Limitations
- C1 specifically focused on data access and query robustness. We have not yet implemented durable asynchronous processing (Celery/Kafka), connection pooling (PgBouncer), or external dependency retries. These are deferred to subsequent phases as per the strict Phase C1 scope.

### I. C2 — Durable Processing & External Attempt State Model
**Status**: COMPLETE ✅

C2 establishes the durable state model that C3 may later execute asynchronously. C2 does not establish 10,000-hospital performance and does not introduce asynchronous infrastructure.

#### A. CURRENT EXTERNAL PROCESSING AUDIT
Previously, external HTTP requests (TPA & HIS Callback) were invoked synchronously within the `TransactionOrchestrator` using `httpx`. The calls were wrapped in generic `try/except Exception` blocks.
- **Success**: Status transitioned to `ADJUDICATED_<status>`.
- **Explicit error / Timeout / Connection failure / Parsing error**: All were caught as generic exceptions and treated as `TPA_ERROR` (failed).
- **Application crash**: Request dropped, DB rolled back, state remained stalled at `SENT_TO_TPA`.
- **Idempotency**: Existing behavior used a unique DB constraint on `Transaction(transaction_id, hospital_id)`. The external attempts themselves were not uniquely guarded.

#### B. NEW DURABLE STATE MODEL (Schemas) — IMPLEMENTED
**1. ExternalOperation** (`app/models/__init__.py`)
Authoritative record for the logical external operation.
- `id` (INTEGER, Primary Key)
- `claim_id` (INTEGER, ForeignKey to `claims.id`, nullable=True)
- `transaction_id` (INTEGER, ForeignKey to `transactions.id`, nullable=True)
- `provider` (String): e.g., "TPA", "HIS_CALLBACK"
- `operation` (String): e.g., "ADJUDICATE"
- `idempotency_key` (String, Unique): Identity of the logical operation.
- `UNIQUE(provider, operation, idempotency_key)` enforced at DB level

**2. ExternalAttempt** (`app/models/__init__.py`)
Current durable state of one execution attempt. Mutates during execution.
- `id` (INTEGER, Primary Key)
- `external_operation_id` (INTEGER, ForeignKey to `external_operations.id`)
- `attempt_number` (Integer, Unique with external_operation_id)
- `state` (String): NOT_DISPATCHED, DISPATCHED, RESPONSE_RECEIVED, UNKNOWN_OUTCOME, FAILED
- `request_metadata`, `response_metadata` (JSONB)
- `error_classification` (String)

**3. ExternalAttemptEvent** (`app/models/__init__.py`)
Append-only audit/history record for every lifecycle transition.
- `id` (INTEGER, Primary Key)
- `external_attempt_id` (INTEGER, ForeignKey to `external_attempts.id`)
- `event_type` (String)
- `from_state` (String)
- `to_state` (String)
- `event_metadata` (JSONB)
- `occurred_at` (DateTime)
- `correlation_id` (String)

#### C. OWNERSHIP INVARIANTS
Every `ExternalOperation` must belong to a known domain entity. A database-level check constraint enforces that `claim_id IS NOT NULL OR transaction_id IS NOT NULL`.

#### D. STATE TRANSITION TABLE (IMPLEMENTED)
- **NOT_DISPATCHED** → **DISPATCHED** (Pre-network step, always committed before network call)
- **NOT_DISPATCHED** → **FAILED** (DNS/Connect failure, validation error before bytes sent)
- **DISPATCHED** → **RESPONSE_RECEIVED** (HTTP 2xx, 4xx, 5xx explicitly parsed or rejected)
- **DISPATCHED** → **UNKNOWN_OUTCOME** (Read/Write Timeout after network connection was established)
- **UNKNOWN_OUTCOME** → **RESPONSE_RECEIVED** / **FAILED** (Reconciliation phase, deferred to C3)

#### E. HTTPX TRANSPORT CLASSIFICATION (IMPLEMENTED)
We map exceptions strictly based on dispatch certainty:
- `httpx.ConnectError` / `httpx.ConnectTimeout` / `httpx.PoolTimeout` (setup failure before transmission): **FAILED** (KNOWN NOT DISPATCHED). Error classification: "CONNECTION_FAILURE".
- `httpx.WriteTimeout` / `httpx.WriteError` (transmission may have begun): **UNKNOWN_OUTCOME** (POSSIBLY DISPATCHED). Error classification: "WRITE_FAILURE".
- `httpx.ReadTimeout` / `httpx.ReadError` (transmission may have occurred): **UNKNOWN_OUTCOME** (POSSIBLY DISPATCHED). Error classification: "READ_FAILURE".
- `httpx.HTTPStatusError`: **RESPONSE_RECEIVED**. Error classification: "HTTP_4XX" or "HTTP_5XX".
- All other exceptions: **UNKNOWN_OUTCOME** ("UNEXPECTED_ERROR") — conservative default.

#### F. DB/NETWORK ATOMICITY BOUNDARY
PostgreSQL cannot atomically commit a state transition together with transmission to an external HTTP server.
- The DB marks `DISPATCHED` immediately before the network call (committed before bytes sent).
- If a process crashes while in `DISPATCHED`, the DB cannot know if the provider received it. The attempt is practically an `UNKNOWN_OUTCOME` and requires reconciliation. We do not pretend database state and physical network transmission can be atomically synchronized.

#### G. IDEMPOTENCY & CONCURRENCY ALGORITHM (IMPLEMENTED)
- **Logical Operation Lock**: `ExternalOperation` acts as the synchronization point.
- **Concurrency Sequence**:
  1. Acquire logical-operation lock: `SELECT ... FROM external_operations WHERE idempotency_key = ? FOR UPDATE`.
  2. Inspect current/latest attempt.
  3. Verify previous attempt is retryable/terminal (FAILED, RESPONSE_RECEIVED).
  4. Determine next attempt number.
  5. Create exactly one next `ExternalAttempt` in a `begin_nested()` savepoint.
  6. Commit.
- **No Python in-memory locks** are used; all coordination is via PostgreSQL.

#### H. INTEGRITYERROR TRANSACTION HANDLING (IMPLEMENTED)
If a fallback unique constraint (`UNIQUE(external_operation_id, attempt_number)`) is hit, it is handled safely without failing the parent transaction via savepoints:
```python
try:
    with db.begin_nested(): # SAVEPOINT
        db.add(new_attempt)
        db.flush()
except IntegrityError:
    # rollback SAVEPOINT is implicit in begin_nested context failure
    raise ValueError(f"Failed to create attempt {n} due to concurrency conflict.")
```

#### I. RETRY CLASSIFICATION (IMPLEMENTED)
- **Potentially retryable**: FAILED (known connection failure before dispatch). A new attempt is permitted via `prepare_attempt()`.
- **Not automatically retryable**: UNKNOWN_OUTCOME (ambiguous whether remote processed). `prepare_attempt()` raises `ValueError` if latest attempt state is `UNKNOWN_OUTCOME`, `NOT_DISPATCHED`, or `DISPATCHED`. Reconciliation is required before retry.
- `UNKNOWN_OUTCOME` is a first-class financial state. It will NOT automatically retry.

#### J. MIGRATION (APPLIED)
- Alembic migration `f52c6d0dcd3d_phase_c2_durable_attempts.py` applied and verified.
- Creates tables: `external_operations`, `external_attempts`, `external_attempt_events`.
- Unique constraint: `UNIQUE(provider, operation, idempotency_key)` on `external_operations`.
- Unique constraint: `UNIQUE(external_operation_id, attempt_number)` on `external_attempts`.
- Check constraint: `claim_id IS NOT NULL OR transaction_id IS NOT NULL`.
- Exactly one Alembic head maintained: `f52c6d0dcd3d`.

#### K. IMPLEMENTATION FILES
- `app/models/__init__.py` — `ExternalOperation`, `ExternalAttempt`, `ExternalAttemptEvent` models
- `app/services/external_attempt_service.py` — `ExternalAttemptService` with state machine
- `app/services/transaction_orchestrator.py` — TPA and HIS callback integrated via `ExternalAttemptService`
- `app/services/his_callback_service.py` — Simplified to raise httpx exceptions (not catch them)
- `alembic/versions/f52c6d0dcd3d_phase_c2_durable_attempts.py` — Migration

#### L. TEST RESULTS (24 new C2 tests, all passing)
`tests/test_c2_durable_attempts.py` — **24/24 passed**

| Test Group | Tests | Coverage |
|---|---|---|
| `TestSuccessPath` | 5 | NOT_DISPATCHED → DISPATCHED → RESPONSE_RECEIVED, metadata persistence |
| `TestConnectionFailurePath` | 3 | ConnectError / ConnectTimeout → FAILED, FAILED_FAILED event |
| `TestUnknownOutcomePath` | 5 | ReadTimeout / WriteTimeout / WriteError → UNKNOWN_OUTCOME; UNKNOWN_OUTCOME blocks retry |
| `TestHttpStatusErrorPath` | 1 | HTTP 5xx → RESPONSE_RECEIVED (not ambiguous, explicit response received) |
| `TestIdempotencyAndAttemptNumbering` | 6 | Same key → same operation; NOT_DISPATCHED/DISPATCHED blocks; FAILED/RESPONSE_RECEIVED allows retry |
| `TestAuditTrail` | 4 | Exact event sequence for all paths; from_state/to_state chain correctness |

**Full test suite**: **72 passed, 0 failed** (48 prior + 24 C2).

#### M. REMAINING LIMITATIONS
- Reconciliation for `UNKNOWN_OUTCOME` states is not yet automated. Manual operator action is required to clear ambiguous attempts before retry is unblocked. Automated reconciliation is deferred to C3.
- No asynchronous workers (Celery/Kafka/Redis) are introduced. C2 is a synchronous, durable state foundation only.
- C3 will introduce the asynchronous processing layer on top of C2 state semantics.

C2 establishes the durable state model that C3 may later execute asynchronously. C2 does not establish 10,000-hospital performance and does not introduce asynchronous infrastructure.

#### A. CURRENT EXTERNAL PROCESSING AUDIT
Currently, external HTTP requests (TPA & HIS Callback) are invoked synchronously within the `TransactionOrchestrator` using `httpx`. The calls are wrapped in generic `try/except Exception` blocks.
- **Success**: Status transitions to `ADJUDICATED_<status>`.
- **Explicit error / Timeout / Connection failure / Parsing error**: All are caught as generic exceptions and treated as `TPA_ERROR` (failed).
- **Application crash**: Request drops, DB rolls back, state remains stalled at `SENT_TO_TPA`.
- **Idempotency**: Existing behavior uses a unique DB constraint on `Transaction(transaction_id, hospital_id)`. The external attempts themselves are not uniquely guarded.

#### B. NEW DURABLE STATE MODEL (Schemas)
**1. ExternalOperation**
Authoritative record for the logical external operation.
- `id` (INTEGER, Primary Key)
- `claim_id` (INTEGER, ForeignKey to `claims.id`, nullable=True)
- `transaction_id` (INTEGER, ForeignKey to `transactions.id`, nullable=True)
- `provider` (String): e.g., "TPA", "HIS_CALLBACK"
- `operation` (String): e.g., "ADJUDICATE"
- `idempotency_key` (String, Unique): Identity of the logical operation.

**2. ExternalAttempt**
Current durable state of one execution attempt. Mutates during execution.
- `id` (INTEGER, Primary Key)
- `external_operation_id` (INTEGER, ForeignKey to `external_operations.id`)
- `attempt_number` (Integer, Unique with external_operation_id)
- `state` (String): NOT_DISPATCHED, DISPATCHED, RESPONSE_RECEIVED, UNKNOWN_OUTCOME, FAILED
- `request_metadata`, `response_metadata` (JSONB)
- `error_classification` (String)

**3. ExternalAttemptEvent**
Append-only audit/history record for every lifecycle transition.
- `id` (INTEGER, Primary Key)
- `external_attempt_id` (INTEGER, ForeignKey to `external_attempts.id`)
- `event_type` (String)
- `from_state` (String)
- `to_state` (String)
- `event_metadata` (JSONB)
- `occurred_at` (DateTime)
- `correlation_id` (String)

#### C. OWNERSHIP INVARIANTS
Every `ExternalOperation` must belong to a known domain entity. A database-level check constraint must enforce that `claim_id IS NOT NULL OR transaction_id IS NOT NULL`.

#### D. STATE TRANSITION TABLE
- **NOT_DISPATCHED** → **DISPATCHED** (Pre-network step)
- **NOT_DISPATCHED** → **FAILED** (DNS/Connect failure, validation error before bytes sent)
- **DISPATCHED** → **RESPONSE_RECEIVED** (HTTP 2xx, 4xx, 5xx explicitly parsed or rejected)
- **DISPATCHED** → **UNKNOWN_OUTCOME** (Read/Write Timeout after network connection was established)
- **UNKNOWN_OUTCOME** → **RESPONSE_RECEIVED** / **FAILED** (Reconciliation phase)

#### E. HTTPX TRANSPORT CLASSIFICATION
We map exceptions strictly based on dispatch certainty:
- `httpx.ConnectError` / `httpx.ConnectTimeout` / `httpx.PoolTimeout` (setup failure before transmission): **FAILED** (KNOWN NOT DISPATCHED). Error classification: "CONNECTION_FAILURE".
- `httpx.WriteTimeout` / `httpx.WriteError` (transmission may have begun): **UNKNOWN_OUTCOME** (POSSIBLY DISPATCHED). Error classification: "WRITE_FAILURE".
- `httpx.ReadTimeout` / `httpx.ReadError` (transmission may have occurred): **UNKNOWN_OUTCOME** (POSSIBLY DISPATCHED). Error classification: "READ_FAILURE".
- `httpx.HTTPStatusError`: **RESPONSE_RECEIVED**. Error classification: "HTTP_4XX" or "HTTP_5XX".

#### F. DB/NETWORK ATOMICITY BOUNDARY
PostgreSQL cannot atomically commit a state transition together with transmission to an external HTTP server.
- The DB marks `DISPATCHED` immediately before the network call.
- If a process crashes while in `DISPATCHED`, the DB cannot know if the provider received it. The attempt is practically an `UNKNOWN_OUTCOME` and requires reconciliation. We do not pretend database state and physical network transmission can be atomically synchronized.

#### G. IDEMPOTENCY & CONCURRENCY ALGORITHM
- **Logical Operation Lock**: We introduce durable coordination at the logical operation level. `ExternalOperation` acts as the synchronization point.
- **Concurrency Sequence**:
  1. Acquire logical-operation lock: `SELECT ... FROM external_operations WHERE idempotency_key = ? FOR UPDATE`.
  2. Inspect current/latest attempt.
  3. Verify previous attempt is retryable/terminal.
  4. Determine next attempt number.
  5. Create exactly one next `ExternalAttempt`.
  6. Commit.
- **No Python in-memory locks** will be used.

#### H. INTEGRITYERROR TRANSACTION HANDLING
If a fallback unique constraint (`UNIQUE(external_operation_id, attempt_number)`) is hit, it must be handled safely without failing the parent transaction:
```python
try:
    with db.begin_nested(): # SAVEPOINT
        db.add(new_attempt)
        db.flush()
except IntegrityError:
    # rollback SAVEPOINT is implicit in begin_nested context failure
    existing_attempt = db.query(ExternalAttempt).filter_by(...).first()
    # continue safely
```
We do not attempt to query using a transaction that remains aborted.

#### I. RETRY CLASSIFICATION
- **Potentially retryable**: Known `NOT_DISPATCHED` transport failures, or explicit HTTP 5xx where provider semantics permit.
- **Not automatically retryable**: `UNKNOWN_OUTCOME`, explicit non-retryable provider responses.
`UNKNOWN_OUTCOME` is a first-class financial state. It will NOT automatically retry. Reconciliation is required.

#### J. MIGRATION APPROACH
- A new, forward-only Alembic migration for `external_operations`, `external_attempts`, and `external_attempt_events`.
- Exact existing types (`INTEGER` for `claim_id` and `transaction_id`) are used.
- We will maintain exactly one Alembic head.

#### K. TEST PLAN
Comprehensive C2 tests will cover:
1. `NOT_DISPATCHED` external failure (broad `httpx.RequestError` does not automatically imply `NOT_DISPATCHED`; only specific connection errors do).
2. Write-side transport failure → `UNKNOWN_OUTCOME` when dispatch cannot be ruled out.
3. Read failure/timeout → `UNKNOWN_OUTCOME`.
4. Successful dispatch + explicit provider failure (HTTP 500).
5. Two concurrent workers attempting retry cannot create two active attempt #2 records.
6. Logical-operation locking is enforced by PostgreSQL.
7. `IntegrityError` uniqueness race safely recovers using savepoint/transaction handling.
8. `ExternalAttemptEvent` records are append-only.
9. State changes create corresponding immutable audit events.
10. `UNKNOWN_OUTCOME` cannot create a retry while unresolved; retry is possible only after explicit reconciliation or a terminal retryable failure.
11. Claim state does not overwrite external attempt state.
12. Existing Phase B behavior and C1 pagination remain unchanged.

---

## PHASE C3 — DURABLE ASYNCHRONOUS WORKER BOUNDARY

**Status**: IMPLEMENTED

### Overview

C3 moves long-running external network operations (TPA adjudication and HIS callback) out of the synchronous HTTP request path into a durable, PostgreSQL-backed background job queue.

**Ingest endpoints now return HTTP 202 Accepted.** The synchronous path completes FWA screening and persists a `BackgroundJob`; the C3 worker executes TPA → HIS asynchronously.

C3 does NOT introduce Redis, Celery, Kafka, RabbitMQ, or external queue infrastructure. PostgreSQL is the durable source of truth for both state and the job queue.

### Synchronous path (HTTP request)

```
Receive → Validate → Code Mapping → Benchmark → FWA
  → Persist Transaction + Claim + ExternalOperation + BackgroundJob
  → COMMIT → HTTP 202 Accepted
```

### Asynchronous path (C3 worker)

```
Worker claims job (SKIP LOCKED)
  → Inspect C2 ExternalAttempt state
  → If safe: execute TPA call via C2 ExternalAttemptService
  → Persist Adjudication + create HIS_CALLBACK job (one commit)
  → HIS_CALLBACK job: deliver callback via C2 ExternalAttemptService
```

### BackgroundJob State Machine

```
PENDING    → CLAIMED      (worker claims via SELECT ... FOR UPDATE SKIP LOCKED)
CLAIMED    → DONE         (success)
CLAIMED    → RETRY_WAIT   (retryable failure; attempts < max_attempts, exponential backoff)
CLAIMED    → EXHAUSTED    (max_attempts reached OR UNKNOWN_OUTCOME/DISPATCHED/RESPONSE_RECEIVED forced)
CLAIMED    → PENDING      (lease expired — crash recovery; re-claimable by any worker)
RETRY_WAIT → PENDING      (next_attempt_at elapsed — polled by housekeeping)
```

### C3 Invariants

1. **UNKNOWN_OUTCOME NEVER causes automatic resend.** A job whose linked ExternalAttempt is `UNKNOWN_OUTCOME` is forced to `EXHAUSTED`. Manual reconciliation is required.
2. **DISPATCHED blocks retry.** A prior call in `DISPATCHED` state means the outcome is ambiguous. The job is forced to `EXHAUSTED` pending reconciliation.
3. **RESPONSE_RECEIVED blocks retry.** A response was already received; do not resend.
4. **`job.attempts` is NOT `ExternalAttempt.attempt_number`.** They are independent counters. A job retry does not automatically create a new ExternalAttempt. The worker inspects C2 state first.
5. **All concurrency via PostgreSQL.** No Python in-memory locks. SKIP LOCKED ensures N-worker safety.
6. **Crash recovery.** Stale `CLAIMED` leases are returned to `PENDING` by the housekeeping poll. Lease recovery does NOT prove the prior call was not dispatched — C2 state must be checked.
7. **Atomic enqueueing.** `BackgroundJob` creation and `ExternalOperation` creation happen in the same database transaction as the intake commit. No job is lost on process crash.

### Database Schema — BackgroundJob

Table: `background_jobs`

| Column | Type | Notes |
|--------|------|-------|
| id | Integer PK | |
| job_type | String(100) | `TPA_ADJUDICATION` or `HIS_CALLBACK` |
| status | String(50) | State machine above |
| payload | JSON | Job-type-specific data |
| transaction_id | FK → transactions | Correlation |
| claim_id | FK → claims | Correlation |
| external_operation_id | FK → external_operations | C2 linkage |
| attempts | Integer | Worker retry count (≠ ExternalAttempt.attempt_number) |
| max_attempts | Integer | Default 5 |
| next_attempt_at | DateTime | Backoff due time |
| last_error | Text | Last failure description |
| error_classification | String | C2-consistent error class |
| worker_id | String | Identity of claiming worker |
| claimed_at | DateTime | When claim began |
| lease_until | DateTime | Lease expiry for crash recovery |
| completed_at | DateTime | DONE or EXHAUSTED timestamp |

Indexes:
- `ix_background_jobs_status_next` on `(status, next_attempt_at)` — queue poll
- `ix_background_jobs_transaction_id` on `(transaction_id)` — correlation
- `ix_background_jobs_ext_op_id` on `(external_operation_id)` — correlation

### Backoff Schedule

| Job attempt | Backoff |
|-------------|---------|
| 1 | 30s |
| 2 | 60s |
| 3 | 120s |
| 4 | 240s |
| 5+ | 3600s (cap) |

### Worker Lifecycle

The worker runs as an asyncio task in the FastAPI lifespan. It starts at app startup and stops cleanly (30-second timeout) at app shutdown. In-flight jobs complete; durable leases ensure crashed jobs are recovered by the next worker start.

The PostgreSQL SKIP LOCKED design is safe for N concurrent workers. Scale by running multiple processes. This is NOT claimed to be sufficient for 10,000 hospitals without load-testing evidence.

### Alembic Migration

Migration: `c3a0b8f9d1e2_phase_c3_background_jobs`
Down revision: `f52c6d0dcd3d` (C2 head)
Current head: `c3a0b8f9d1e2`

### API Contract Changes

| Endpoint | Before C3 | After C3 |
|----------|-----------|----------|
| `POST /api/v1/transactions` | 201 Created | **202 Accepted** |
| `POST /api/v1/demo/submit` | 201 Created | **202 Accepted** |
| `POST /api/v1/integrations/rest/submit` | 201 Created | **202 Accepted** |
| All GET endpoints | unchanged | unchanged |

**202 semantics:** FWA screening is synchronous and complete. TPA adjudication and HIS callback are in progress via the C3 worker. Poll the transaction detail endpoint for final status.

### Limitations and Known Gaps (as implemented)

- **DB/network atomicity**: PostgreSQL cannot atomically commit `DISPATCHED` with physical HTTP transmission. If a process crashes between the `DISPATCHED` commit and `RESPONSE_RECEIVED` commit, the ExternalAttempt stays `DISPATCHED` and requires reconciliation. This is an inherent distributed-systems limitation, not a C3 defect.
- **No UNKNOWN_OUTCOME reconciliation UI** in this phase. Exhausted jobs with `UNKNOWN_OUTCOME` require manual operator intervention.
- **Single worker instance** in the FastAPI lifespan. The DB design is N-worker safe, but the current deployment runs one worker.
- **SQLite test limitation**: SKIP LOCKED is PostgreSQL-only. Tests use SQLite and fall back to sequential claiming (safe for single-threaded tests).
- **No production capacity claim**: This design is NOT claimed to support 10,000 hospitals without load-testing evidence.
