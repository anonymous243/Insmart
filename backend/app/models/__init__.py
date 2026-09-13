import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    String, Integer, Float, Boolean, DateTime, Text,
    ForeignKey, JSON, UniqueConstraint, Numeric, Index, CheckConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


def utcnow():
    return datetime.now(timezone.utc)


class TerminologySystem(Base):
    __tablename__ = "terminology_systems"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=True)
    country: Mapped[str] = mapped_column(String(50), nullable=True)
    source_url: Mapped[str] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    patient_reference: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    age: Mapped[int] = mapped_column(Integer, nullable=True)
    sex: Mapped[str] = mapped_column(String(10), nullable=True)
    dob: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    province: Mapped[str] = mapped_column(String(100), nullable=True)
    insurance_reference: Mapped[str] = mapped_column(String(100), nullable=True)
    synthetic_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Hospital(Base):
    __tablename__ = "hospitals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    hospital_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    hospital_name: Mapped[str] = mapped_column(String(200), nullable=False)
    integration_type: Mapped[str] = mapped_column(String(50), default="API")
    response_endpoint: Mapped[str] = mapped_column(String(500), nullable=True)
    api_key_hash: Mapped[str] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    hospital_codes: Mapped[list["HospitalCode"]] = relationship("HospitalCode", back_populates="hospital")
    transactions: Mapped[list["Transaction"]] = relationship("Transaction", back_populates="hospital")
    code_mappings: Mapped[list["CodeMapping"]] = relationship("CodeMapping", back_populates="hospital")


class HospitalCode(Base):
    __tablename__ = "hospital_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    hospital_id: Mapped[int] = mapped_column(Integer, ForeignKey("hospitals.id"), nullable=False)
    hospital_code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=True)
    source_system: Mapped[str] = mapped_column(String(100), nullable=True)
    version: Mapped[str] = mapped_column(String(20), default="1.0")
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    synthetic_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    effective_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("hospital_id", "hospital_code", name="uq_hospital_code"),)

    hospital: Mapped["Hospital"] = relationship("Hospital", back_populates="hospital_codes")
    code_mappings: Mapped[list["CodeMapping"]] = relationship("CodeMapping", back_populates="hospital_code_obj")


class CommonCode(Base):
    __tablename__ = "common_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    common_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=True)
    terminology_system: Mapped[str] = mapped_column(String(100), nullable=True)
    terminology_code: Mapped[str] = mapped_column(String(100), nullable=True)
    terminology_display: Mapped[str] = mapped_column(String(300), nullable=True)
    terminology_version: Mapped[str] = mapped_column(String(50), nullable=True)
    country: Mapped[str] = mapped_column(String(50), nullable=True)
    source: Mapped[str] = mapped_column(String(100), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(50), nullable=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    effective_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[str] = mapped_column(String(20), default="1.0")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    code_mappings: Mapped[list["CodeMapping"]] = relationship("CodeMapping", back_populates="common_code_obj")
    price_benchmarks: Mapped[list["PriceBenchmark"]] = relationship("PriceBenchmark", back_populates="common_code_obj")


class CodeMapping(Base):
    __tablename__ = "code_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    hospital_id: Mapped[int] = mapped_column(Integer, ForeignKey("hospitals.id"), nullable=False)
    hospital_code_id: Mapped[int] = mapped_column(Integer, ForeignKey("hospital_codes.id"), nullable=False)
    common_code_id: Mapped[int] = mapped_column(Integer, ForeignKey("common_codes.id"), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    mapping_status: Mapped[str] = mapped_column(String(20), default="MAPPED")
    mapping_method: Mapped[str] = mapped_column(String(50), nullable=True)
    mapped_by: Mapped[str] = mapped_column(String(100), nullable=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    effective_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[str] = mapped_column(String(20), default="1.0")
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("hospital_id", "hospital_code_id", name="uq_mapping"),)

    hospital: Mapped["Hospital"] = relationship("Hospital", back_populates="code_mappings")
    hospital_code_obj: Mapped["HospitalCode"] = relationship("HospitalCode", back_populates="code_mappings")
    common_code_obj: Mapped["CommonCode"] = relationship("CommonCode", back_populates="code_mappings")


class PriceBenchmark(Base):
    __tablename__ = "price_benchmarks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    common_code_id: Mapped[int] = mapped_column(Integer, ForeignKey("common_codes.id"), nullable=False)
    benchmark_price: Mapped[float] = mapped_column(Float, nullable=False)
    allowed_variance_percent: Mapped[float] = mapped_column(Float, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    effective_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    common_code_obj: Mapped["CommonCode"] = relationship("CommonCode", back_populates="price_benchmarks")


class FWARule(Base):
    __tablename__ = "fwa_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    rule_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    rule_name: Mapped[str] = mapped_column(String(200), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(50), nullable=False)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    transaction_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    hospital_id: Mapped[int] = mapped_column(Integer, ForeignKey("hospitals.id"), nullable=False)
    patient_reference: Mapped[str] = mapped_column(String(100), nullable=False)
    submitted_amount: Mapped[float] = mapped_column(Float, default=0.0)
    normalized_amount: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(50), default="RECEIVED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("hospital_id", "transaction_id", name="uq_hospital_transaction"),)

    hospital: Mapped["Hospital"] = relationship("Hospital", back_populates="transactions")
    items: Mapped[list["TransactionItem"]] = relationship("TransactionItem", back_populates="transaction")
    fwa_results: Mapped[list["FWAResult"]] = relationship("FWAResult", back_populates="transaction")
    adjudication: Mapped["Adjudication"] = relationship("Adjudication", back_populates="transaction", uselist=False)
    integration_events: Mapped[list["IntegrationEvent"]] = relationship("IntegrationEvent", back_populates="transaction")


class TransactionItem(Base):
    __tablename__ = "transaction_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    transaction_id: Mapped[int] = mapped_column(Integer, ForeignKey("transactions.id"), nullable=False)
    hospital_code: Mapped[str] = mapped_column(String(50), nullable=False)
    common_code: Mapped[str] = mapped_column(String(50), nullable=True)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    benchmark_price: Mapped[float] = mapped_column(Float, nullable=True)
    benchmark_status: Mapped[str] = mapped_column(String(20), nullable=True)
    mapping_status: Mapped[str] = mapped_column(String(20), nullable=True)
    mapping_confidence: Mapped[float] = mapped_column(Float, nullable=True)
    allowed_maximum: Mapped[float] = mapped_column(Float, nullable=True)
    variance_percent: Mapped[float] = mapped_column(Float, nullable=True)

    transaction: Mapped["Transaction"] = relationship("Transaction", back_populates="items")


class FWAResult(Base):
    __tablename__ = "fwa_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    transaction_id: Mapped[int] = mapped_column(Integer, ForeignKey("transactions.id"), nullable=False)
    rule_code: Mapped[str] = mapped_column(String(50), nullable=False)
    rule_name: Mapped[str] = mapped_column(String(200), nullable=False)
    result: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    transaction: Mapped["Transaction"] = relationship("Transaction", back_populates="fwa_results")


class Adjudication(Base):
    __tablename__ = "adjudications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    transaction_id: Mapped[int] = mapped_column(Integer, ForeignKey("transactions.id"), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    approved_amount: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(Text, nullable=True)
    reference: Mapped[str] = mapped_column(String(100), nullable=True)
    his_delivery_status: Mapped[str] = mapped_column(String(50), nullable=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    transaction: Mapped["Transaction"] = relationship("Transaction", back_populates="adjudication")


class IntegrationEvent(Base):
    __tablename__ = "integration_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    transaction_id: Mapped[int] = mapped_column(Integer, ForeignKey("transactions.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    transaction: Mapped["Transaction"] = relationship("Transaction", back_populates="integration_events")

class CommercialPolicy(Base):
    __tablename__ = "commercial_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    policy_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    insurer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    policy_type: Mapped[str] = mapped_column(String(100), nullable=True) # e.g. "FAMILY", "CORPORATE"
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    members: Mapped[list["Member"]] = relationship("Member", back_populates="policy")
    coverage_rules: Mapped[list["CoverageRule"]] = relationship("CoverageRule", back_populates="policy")


class Member(Base):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    member_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    policy_id: Mapped[int] = mapped_column(Integer, ForeignKey("commercial_policies.id"), nullable=False)
    patient_id: Mapped[int] = mapped_column(Integer, ForeignKey("patients.id"), nullable=False)
    relationship_to_principal: Mapped[str] = mapped_column(String(50), default="SELF")
    status: Mapped[str] = mapped_column(String(50), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    policy: Mapped["CommercialPolicy"] = relationship("CommercialPolicy", back_populates="members")
    patient: Mapped["Patient"] = relationship("Patient")
    claims: Mapped[list["Claim"]] = relationship("Claim", back_populates="member")


class CoverageRule(Base):
    __tablename__ = "coverage_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    policy_id: Mapped[int] = mapped_column(Integer, ForeignKey("commercial_policies.id"), nullable=False)
    common_code_id: Mapped[int] = mapped_column(Integer, ForeignKey("common_codes.id"), nullable=False)
    coverage_percent: Mapped[float] = mapped_column(Numeric(5, 2), default=100.0)
    copay_amount: Mapped[float] = mapped_column(Numeric(15, 2), default=0.0)
    max_amount: Mapped[float] = mapped_column(Numeric(15, 2), nullable=True)
    requires_preauth: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    policy: Mapped["CommercialPolicy"] = relationship("CommercialPolicy", back_populates="coverage_rules")
    common_code: Mapped["CommonCode"] = relationship("CommonCode")


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    claim_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    hospital_id: Mapped[int] = mapped_column(Integer, ForeignKey("hospitals.id"), nullable=False)
    patient_id: Mapped[int] = mapped_column(Integer, ForeignKey("patients.id"), nullable=True)
    member_id: Mapped[int] = mapped_column(Integer, ForeignKey("members.id"), nullable=True)
    policy_id: Mapped[int] = mapped_column(Integer, ForeignKey("commercial_policies.id"), nullable=True)
    transaction_id: Mapped[int] = mapped_column(Integer, ForeignKey("transactions.id"), unique=True, nullable=False) # Link to integration envelope
    
    total_billed_amount: Mapped[float] = mapped_column(Numeric(15, 2), default=0.0)
    total_approved_amount: Mapped[float] = mapped_column(Numeric(15, 2), default=0.0)
    total_patient_responsibility: Mapped[float] = mapped_column(Numeric(15, 2), default=0.0)
    
    status: Mapped[str] = mapped_column(String(50), default="RECEIVED") # RECEIVED, IN_REVIEW, APPROVED, REJECTED, PENDING_ELIGIBILITY
    service_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("ix_claims_hospital_created", "hospital_id", "created_at"),
        Index("ix_claims_hospital_status", "hospital_id", "status"),
    )

    hospital: Mapped["Hospital"] = relationship("Hospital")
    patient: Mapped["Patient"] = relationship("Patient")
    member: Mapped["Member"] = relationship("Member", back_populates="claims")
    policy: Mapped["CommercialPolicy"] = relationship("CommercialPolicy")
    transaction: Mapped["Transaction"] = relationship("Transaction")
    items: Mapped[list["ClaimItem"]] = relationship("ClaimItem", back_populates="claim")


class ClaimItem(Base):
    __tablename__ = "claim_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    claim_id: Mapped[int] = mapped_column(Integer, ForeignKey("claims.id"), nullable=False, index=True)
    hospital_code_id: Mapped[int] = mapped_column(Integer, ForeignKey("hospital_codes.id"), nullable=True)
    common_code_id: Mapped[int] = mapped_column(Integer, ForeignKey("common_codes.id"), nullable=True)
    
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    billed_unit_price: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    billed_total: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    
    approved_total: Mapped[float] = mapped_column(Numeric(15, 2), default=0.0)
    patient_responsibility: Mapped[float] = mapped_column(Numeric(15, 2), default=0.0)
    
    status: Mapped[str] = mapped_column(String(50), default="PENDING")
    denial_reason: Mapped[str] = mapped_column(Text, nullable=True)

    claim: Mapped["Claim"] = relationship("Claim", back_populates="items")
    hospital_code: Mapped["HospitalCode"] = relationship("HospitalCode")
    common_code: Mapped["CommonCode"] = relationship("CommonCode")


class ExternalOperation(Base):
    __tablename__ = "external_operations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    claim_id: Mapped[int] = mapped_column(Integer, ForeignKey("claims.id"), nullable=True)
    transaction_id: Mapped[int] = mapped_column(Integer, ForeignKey("transactions.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("provider", "operation", "idempotency_key", name="uq_external_operation_identity"),
        CheckConstraint("claim_id IS NOT NULL OR transaction_id IS NOT NULL", name="ck_external_operation_owner"),
    )

    attempts: Mapped[list["ExternalAttempt"]] = relationship("ExternalAttempt", back_populates="operation_obj")


class ExternalAttempt(Base):
    __tablename__ = "external_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    external_operation_id: Mapped[int] = mapped_column(Integer, ForeignKey("external_operations.id"), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(50), default="NOT_DISPATCHED")
    request_metadata: Mapped[dict] = mapped_column(JSON, nullable=True)
    response_metadata: Mapped[dict] = mapped_column(JSON, nullable=True)
    error_classification: Mapped[str] = mapped_column(String(100), nullable=True)
    dispatched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    response_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("external_operation_id", "attempt_number", name="uq_external_attempt_number"),
    )

    operation_obj: Mapped["ExternalOperation"] = relationship("ExternalOperation", back_populates="attempts")
    events: Mapped[list["ExternalAttemptEvent"]] = relationship("ExternalAttemptEvent", back_populates="attempt_obj")


class ExternalAttemptEvent(Base):
    __tablename__ = "external_attempt_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    external_attempt_id: Mapped[int] = mapped_column(Integer, ForeignKey("external_attempts.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    from_state: Mapped[str] = mapped_column(String(50), nullable=True)
    to_state: Mapped[str] = mapped_column(String(50), nullable=False)
    event_metadata: Mapped[dict] = mapped_column(JSON, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    correlation_id: Mapped[str] = mapped_column(String(200), nullable=True)

    attempt_obj: Mapped["ExternalAttempt"] = relationship("ExternalAttempt", back_populates="events")


class ExternalReconciliation(Base):
    """
    Phase C4 — Durable reconciliation for UNKNOWN_OUTCOME external attempts.

    Reconciliation state machine:
      PENDING      → IN_PROGRESS    (worker claims reconciliation job)
      IN_PROGRESS  → RESOLVED       (provider outcome determined)
      IN_PROGRESS  → RETRY_WAIT     (reconciliation failure; attempts < max_attempts, backoff)
      IN_PROGRESS  → EXHAUSTED      (max reconciliation attempts reached)
      RETRY_WAIT   → PENDING        (next_attempt_at elapsed)

    CRITICAL INVARIANT:
      Reconciliation NEVER creates a new ExternalAttempt automatically.
      RESOLVED outcome determines whether a new ExternalAttempt is permitted:
        - FOUND_SUCCESS / FOUND_REJECTED / FOUND_REVIEW: outcome known, update business state
        - NOT_FOUND: only permits new ExternalAttempt if provider semantics + idempotency allow
        - STILL_PROCESSING / PROVIDER_ERROR / UNKNOWN: remains unresolved, no new dispatch
    """
    __tablename__ = "external_reconciliations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    external_operation_id: Mapped[int] = mapped_column(Integer, ForeignKey("external_operations.id"), nullable=False)
    external_attempt_id: Mapped[int] = mapped_column(Integer, ForeignKey("external_attempts.id"), nullable=False)
    reconciliation_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="PENDING", nullable=False)
    provider_outcome: Mapped[str] = mapped_column(String(50), nullable=True)  # FOUND_SUCCESS, FOUND_REJECTED, FOUND_REVIEW, NOT_FOUND, STILL_PROCESSING, PROVIDER_ERROR, UNKNOWN
    provider_reference: Mapped[str] = mapped_column(String(200), nullable=True)
    lookup_key: Mapped[str] = mapped_column(String(200), nullable=True)  # e.g., transaction_id, claim_id
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    last_error: Mapped[str] = mapped_column(Text, nullable=True)
    error_classification: Mapped[str] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("external_operation_id", "reconciliation_number", name="uq_external_reconciliation_number"),
        Index("ix_external_reconciliations_ext_op_status", "external_operation_id", "status"),
        Index("ix_external_reconciliations_ext_attempt_id", "external_attempt_id"),
    )

    external_operation: Mapped["ExternalOperation"] = relationship("ExternalOperation")
    external_attempt: Mapped["ExternalAttempt"] = relationship("ExternalAttempt")


class BackgroundJob(Base):
    """
    Phase C3 — PostgreSQL-backed durable job queue.

    Job state machine:
      PENDING    → CLAIMED      (worker claims job using SKIP LOCKED)
      CLAIMED    → DONE         (successful execution)
      CLAIMED    → RETRY_WAIT   (retryable failure; attempts < max_attempts)
      CLAIMED    → EXHAUSTED    (max_attempts reached OR UNKNOWN_OUTCOME/DISPATCHED detected)
      CLAIMED    → PENDING      (lease expired — crash recovery; re-claimable)
      RETRY_WAIT → PENDING      (next_attempt_at elapsed — ready for next claim)

    CRITICAL INVARIANT:
      Job state is NOT ExternalAttempt state.
      A job retry does NOT automatically create a new ExternalAttempt.
      The worker MUST inspect C2 ExternalOperation/ExternalAttempt state before any dispatch.
      UNKNOWN_OUTCOME forces EXHAUSTED — never blind resend.
    """
    __tablename__ = "background_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)  # TPA_ADJUDICATION | HIS_CALLBACK
    status: Mapped[str] = mapped_column(String(50), default="PENDING", nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=True)

    # Correlation — trace job → transaction → claim → external operation
    transaction_id: Mapped[int] = mapped_column(Integer, ForeignKey("transactions.id"), nullable=True)
    claim_id: Mapped[int] = mapped_column(Integer, ForeignKey("claims.id"), nullable=True)
    external_operation_id: Mapped[int] = mapped_column(Integer, ForeignKey("external_operations.id"), nullable=True)

    # Retry metadata — distinct from ExternalAttempt.attempt_number
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_error: Mapped[str] = mapped_column(Text, nullable=True)
    error_classification: Mapped[str] = mapped_column(String(100), nullable=True)

    # Lease / claiming fields
    worker_id: Mapped[str] = mapped_column(String(200), nullable=True)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    # Terminal timestamps
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        # Primary queue-poll index: find eligible PENDING jobs ordered by due time
        Index("ix_background_jobs_status_next", "status", "next_attempt_at"),
        # Correlation lookups
        Index("ix_background_jobs_transaction_id", "transaction_id"),
        Index("ix_background_jobs_ext_op_id", "external_operation_id"),
    )


from app.models.user import User, FacilityUser
