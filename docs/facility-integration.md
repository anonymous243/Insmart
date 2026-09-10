# Vietnam Healthcare Claims - Facility Integration Guide

## Architecture Overview
The platform serves as a centralized hub bridging heterogeneous hospital HIS (Health Information Systems) and third-party administrators (TPAs) or Core government adjudicators. 

It handles:
1. **Dynamic Code Mapping**: Translating proprietary local hospital codes to standard Vietnamese healthcare codes.
2. **Benchmarking & FWA**: Evaluating submitted prices against national averages and flagging Fraud, Waste, and Abuse.
3. **Orchestrated Adjudication**: Forwarding validated claims to the simulated TPA endpoint.
4. **HIS Callbacks**: Providing asynchronous HTTP POST callbacks to facilities regarding final claim decisions.

## Tenant Isolation & Security
- **Authentication**: Facilities authenticate via JWT. Passwords are securely hashed via bcrypt.
- **Data Privacy**: Transactions and facility configurations are strictly isolated. Facilities cannot view cross-tenant data. 
- **API Keys**: Integration interfaces (like the REST Adapter) utilize API Key hashes for seamless but secure machine-to-machine submissions.

## Data Model & Workflows

### 1. Code Mapping 
Each facility maintains a mapping table (`CodeMapping`) that connects their `HospitalCode` to a global `CommonCode`. Claims submitted with unmapped codes are immediately rejected with a `VALIDATION_FAILED` status.

### 2. Transaction Pipeline
1. **Submit**: Client sends a POST to `/api/v1/transactions` (or `/api/v1/integrations/rest/submit`).
2. **Idempotency**: Checked against `transaction_id` per facility.
3. **Map**: Codes mapped via `CodeMappingService`.
4. **Benchmark**: Evaluated via `BenchmarkService`.
5. **FWA**: Analyzed for suspicious patterns (e.g. FWA-003: Price Anomaly).
6. **TPA Adjudication**: Sent to the upstream TPA processor.
7. **Callback**: A final JSON payload is pushed back to the facility's `response_endpoint`.

## Production Limitations (As of v1)
* **Real-time Government Connectivity**: The platform operates with simulated TPA/Core endpoints. Real government integration is not yet implemented.
* **Synchronous Bottlenecks**: High-volume asynchronous processing (Kafka/RabbitMQ) is not yet integrated.
* **Float Precision**: Financial calculations currently utilize Floats; transition to Decimals is recommended to prevent precision loss in heavy VND aggregations.
* **JWT Secret**: Current configurations may utilize a 30-byte JWT secret which falls below the recommended 32-byte SHA256 minimum. 

## Integration Points
* **Admin UI / Tools**: `GET /api/v1/transactions` (Global view)
* **Facility Portal**: `GET /api/v1/facility/history` (Tenant isolated)
* **REST Adapter**: `POST /api/v1/integrations/rest/submit` 
