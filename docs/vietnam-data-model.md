# Vietnam Healthcare MVP Data Model

This document outlines the synthetic data model used in the Vietnam claims adjudication platform MVP. The MVP demonstrates how to ingest data from heterogeneous Hospital Information Systems (HIS) and normalize it to a centralized standard.

## 1. Terminology Systems

The `terminology_systems` table tracks standard classifications used in Vietnam, providing the foundation for normalized clinical and billing data.

- **Vietnam ICD-10 (2024)**: Diagnosis codes (Reference)
- **Vietnam LOINC (2.76)**: Laboratory observations (Reference)
- **Vietnam SNOMED CT subset (2024)**: Clinical terms (Reference)
- **BHYT Terminology**: Decision 1804/QĐ-BYT compliant terminology (Reference)
- **Central Common Code Master**: Our internal, verified taxonomy used by the TPA Core and FWA engines.

## 2. Hospitals and Hospital Codes

Each connected hospital retains its local billing and procedure codes, reflecting reality where no two HIS environments are perfectly aligned.

- **H001: Hanoi General Hospital (Demo)**: Uses alphanumeric codes like `CARD001`, `XR001`.
- **H002: Saigon Medical Center (Demo)**: Uses prefixed hyphenated codes like `CC-102`, `RAD-09`.
- **H003: Central Vietnam Hospital (Demo)**: Uses department-based codes like `CARD-C01`, `XR-CHEST`.

These local codes are mapped directly to the **Central Common Code Master** using the `code_mappings` table.

## 3. The Central Common Code Master

The MVP maps heterogeneous hospital inputs to standardized `common_codes`:

| Category | Example Code | Description |
| :--- | :--- | :--- |
| CONSULTATION | `CONS-CARD` | Cardiology Consultation |
| PROCEDURE | `PROC-WOUND` | Wound Care |
| RADIOLOGY | `XR-CHEST` | Chest X-Ray |
| LABORATORY | `LAB-CBC` | Complete Blood Count |

*When a transaction arrives, the orchestrator immediately resolves the hospital's local code to the `common_code` before any processing occurs.*

## 4. Patients

Patient demographics are tracked in the `patients` table. They include localized data such as Vietnamese provinces (Hanoi, Ho Chi Minh City, Da Nang, etc.) and synthetic BHYT (Vietnam Social Security) references (e.g., `BHYT-1234567`).

## 5. FWA Rules and Benchmarks

Fraud, Waste, and Abuse (FWA) detection and Price Benchmarking operate exclusively on the **Central Common Code Master**.

- **Benchmarks**: Price caps are established for common codes (e.g., `CONS-CARD` max 900 ₫).
- **FWA-001**: Duplicate Service detection.
- **FWA-002**: Frequency checks.
- **FWA-003**: Price Anomalies.
- **FWA-004**: Unusual Quantities (e.g., billing 6 ECGs).
- **FWA-005**: Unusual Same-Day Combinations.

## Summary

This architecture guarantees that the core adjudication logic (FWA & TPA rules) remains isolated from the complexity of individual HIS implementations. As new hospitals are onboarded, only the `hospital_codes` and `code_mappings` tables require updating.
