with open('docs/production-chi-foundation-plan.md', 'a') as f:
    f.write("""

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

### B. SCALE ASSUMPTIONS
- **Hospitals**: 10,000 active facilities.
- **Claims/Day/Hospital**: ~200 (Baseline), ~1,000 (High).
- **Total Claims/Day**: 2,000,000 (Baseline) to 10,000,000 (High).
- **Peak Claims/Second**: ~100 (Baseline), ~500 (High).
- **Concurrent Users**: ~500 Admin users, ~15,000 Facility users.
- **Retention**: Active database retention of 13 months before archival.
- **Storage Growth**: ~5-10 GB/day.

### C. IDENTIFIED BOTTLENECKS
1. **N+1 Queries**: `routes_facility.py:get_facility_codes` performs a `db.query(CodeMapping).first()` inside a loop over local hospital codes.
2. **Unbounded/LIMIT Pagination**: Admin and Facility lists use hardcoded `.limit(200)` without cursor/offset capabilities, making deep history retrieval impossible.
3. **Synchronous Callbacks**: `HISCallbackService` blocks the main request thread while HTTP posting to the HIS, exposing the API to external timeout cascades.
4. **Database Connection Pool**: FastAPI running multiple workers with the default SQLAlchemy pool size (5) will quickly exhaust connections or queue under peak 500 TPS load.

### D. REQUIRED CHANGES
1. **Query/Index Hardening**:
   - Refactor `get_facility_codes` to use a single `IN` clause or SQL `JOIN` instead of N+1.
   - Implement keyset/cursor pagination (`cursor_created_at`, `cursor_id`) for high-volume timelines (`/history`, `/transactions`) to avoid `OFFSET` scanning penalties.
2. **Integration Durability (Async Boundary)**:
   - Synchronous processing remains for (Ingestion, Validation, Canonicalization).
   - *Async Boundary*: Move External TPA network calls and HIS callbacks to a durable background worker queue (e.g., Celery/Redis or PostgreSQL LISTEN/NOTIFY minimal queue) to isolate network latency from ingestion capacity.
3. **Connection Pool Tuning**: Increase SQLAlchemy `pool_size` (e.g., 50) and `max_overflow` (e.g., 20), and evaluate PgBouncer for transaction-level pooling.
4. **Failure Isolation**: Implement strict timeouts and circuit breakers on HIS and TPA HTTP adapters.

### E. CHANGES NOT JUSTIFIED YET
- **Microservices Architecture**: The modular monolith remains highly cohesive and capable of scaling horizontally.
- **Database Partitioning**: Until the database exceeds ~1-2TB (approx 12-18 months of baseline load), native B-Tree indexes on `hospital_id` + `created_at` will suffice.
- **Distributed Caching (Redis for caching)**: Read workloads (code mappings, hospital metadata) are highly cacheable in-process (LRU cache) without requiring a Redis cluster.

### F. LOAD-TEST PLAN
- **Scenarios**: 1,000, 5,000, and 10,000 simulated hospital profiles.
- **Metrics**: Assert p95 latency < 500ms, 0% error rate, and PgBouncer/PostgreSQL CPU < 70%.
- **Workload Mix**: 80% claim submissions (concurrent), 15% Facility history queries, 5% Central Admin filtered searches.

### G. SCALING TRIGGERS
- Extract Background Workers: If p95 ingestion latency exceeds 1.5s due to TPA/HIS timeouts.
- Table Partitioning (PostgreSQL `PARTITION BY RANGE`): When `claims` table exceeds 100 million rows.
- Read Replicas: When Central Admin complex aggregation queries cause >30% baseline CPU spike on the primary database.

### H. RECOMMENDED NEXT IMPLEMENTATION PHASE
**C1 — Query/index hardening**: Refactor the N+1 code mapping queries and implement cursor-based pagination for Admin/Facility listings to establish a safe database access pattern before scaling integrations.
""")
