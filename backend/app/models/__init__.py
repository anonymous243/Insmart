import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    String, Integer, Float, Boolean, DateTime, Text,
    ForeignKey, JSON, UniqueConstraint
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

from app.models.user import User, FacilityUser
