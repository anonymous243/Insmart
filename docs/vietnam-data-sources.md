# Vietnam Healthcare MVP Data Sources & Assumptions

This document outlines the synthetic nature of the data in the MVP and details the assumptions made for the "Central Code Master" concept.

## 1. Synthetic Data Disclaimer

All data within this MVP—including hospital names, terminology systems, common codes, price benchmarks, and patient demographics—is **100% synthetic**. It was generated programmatically for demonstration purposes and does not represent real-world clinical data, actual hospital pricing, or real patient health records.

## 2. Terminology Assumptions

For this MVP, we assume the existence of a **"Central Common Code Master"**. In a production environment, this central code system would likely be heavily influenced by or directly mapped to official standards such as:
- **Decision 1804/QĐ-BYT** (Vietnam Social Security terminology)
- **Vietnam ICD-10** (for diagnoses, though this MVP primarily focuses on procedure/billing codes)
- **SNOMED CT / LOINC**

We assume that the Central API hub maintains a robust mapping engine that translates disparate HIS codes into this single vocabulary.

## 3. Financial Assumptions

- **Currency**: The platform simulates the Vietnamese Đồng (VND, `₫`), however, for simplicity in the prototype UI, numbers are scaled down to smaller integer values (e.g., 750 ₫ instead of 750,000 ₫).
- **Benchmarks**: Price caps are static in this MVP. In production, these benchmarks would be dynamic, varying by hospital tier (Tuyến trung ương, Tuyến tỉnh, Tuyến huyện) and geographic region.

## 4. Integration Assumptions

- We assume hospitals submit claims synchronously to the Central API Hub via a standardized JSON payload (`POST /api/v1/transactions`).
- We assume the Central API Hub is capable of making outbound webhooks or callbacks to the HIS to deliver adjudication results.
- The TPA Core is represented as an external mock microservice. In reality, it would be a complex rules engine.

## 5. FWA (Fraud, Waste, Abuse) Assumptions

The FWA rules implemented (`FWA-001` through `FWA-005`) are simplified heuristics. A production FWA engine would leverage machine learning models, historical anomaly detection, and complex clinical rule sets (e.g., checking for unbundled procedures).
