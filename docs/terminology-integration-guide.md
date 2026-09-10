# Terminology Integration Guide

This guide describes how to integrate and manage terminology systems within the Vietnam Healthcare MVP.

## 1. Overview

The MVP uses a "Central Code Master" approach. Instead of forcing hospitals to adopt a new HIS or change their internal billing codes, the platform ingests their local codes and maps them to a centralized taxonomy. This allows the Fraud, Waste, and Abuse (FWA) engine and Adjudication logic to operate on normalized data.

## 2. Managing Terminology Systems

The `terminology_systems` table stores metadata about available terminologies:

- `name`: The name of the terminology (e.g., "Vietnam ICD-10", "Central Common Code Master")
- `version`: The version string (e.g., "2024", "1.0")
- `country`: ISO code (e.g., "VN")
- `source_url`: URL for the terminology documentation or API.
- `status`: "ACTIVE", "INACTIVE", etc.
- `verified`: Boolean indicating if the terminology is officially verified for adjudication use.

Only the "Central Common Code Master" is used directly for rules and benchmarks in this MVP. Other systems (ICD-10, LOINC) are provided for reference and future mapping.

## 3. Registering Common Codes

The `common_codes` table stores the actual concepts used by the platform:

- `common_code`: The unique identifier (e.g., `CONS-CARD`).
- `description`: Human-readable description (e.g., "Cardiology Consultation").
- `category`: Conceptual grouping (e.g., `CONSULTATION`, `PROCEDURE`, `RADIOLOGY`).
- `terminology_system`: Foreign key to `terminology_systems`.

## 4. Mapping Hospital Codes

When a new hospital is onboarded, their local codes must be mapped.

1. **Register Hospital Codes**: Insert the HIS-specific codes into the `hospital_codes` table.
2. **Create Code Mappings**: Insert records into the `code_mappings` table, linking a `hospital_code_id` to a `common_code_id`.
   - `mapping_status` should be "MAPPED".
   - `confidence` indicates the certainty of the mapping (1.0 = 100%).

## 5. The Normalization Process

When the `TransactionOrchestrator` receives a `TransactionIn` payload:

1. It extracts the `hospital_id` and the submitted items.
2. For each item, it looks up the local `hospital_code`.
3. It queries the `code_mappings` table for an active mapping.
4. If found, the `common_code` is attached to the `TransactionItem`.
5. If *any* code in the transaction is unmapped, the transaction is rejected with a `VALIDATION_FAILED` status, ensuring that the FWA engine never operates on unknown data.

## 6. Best Practices

- **Never modify historical mappings**: If a hospital changes the meaning of a local code, create a new mapping version rather than overwriting the old one. This preserves historical adjudication accuracy.
- **Audit Logs**: Ensure all mapping changes are audited.
- **Regular Updates**: Terminology systems (like ICD-10 or BHYT decisions) update periodically. Have a process to ingest new versions and remap as necessary.
