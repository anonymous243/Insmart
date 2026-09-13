from datetime import datetime
from typing import Optional, Any, Generic, TypeVar, List
from pydantic import BaseModel, Field

T = TypeVar("T")

class PaginationResponse(BaseModel, Generic[T]):
    items: List[T]
    next_cursor: Optional[str] = None
    has_more: bool = False

# ── Hospital ────────────────────────────────────────────────────────────────

class HospitalOut(BaseModel):
    id: int
    hospital_code: str
    hospital_name: str
    integration_type: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Code Mapping ─────────────────────────────────────────────────────────────

class CodeMappingRow(BaseModel):
    hospital_code: str
    hospital_name: str
    local_code: str
    local_description: str
    common_code: str
    common_description: str
    category: str
    mapping_status: str
    confidence: float
    terminology_system: Optional[str] = None
    mapping_method: Optional[str] = None
    version: Optional[str] = None
    effective_from: Optional[datetime] = None

    model_config = {"from_attributes": True}

class BenchmarkRow(BaseModel):
    common_code: str
    benchmark_price: float
    allowed_variance_percent: float

    model_config = {"from_attributes": True}


# ── Transaction Submit ────────────────────────────────────────────────────────

class TransactionItemIn(BaseModel):
    hospital_code: str = Field(..., min_length=1, max_length=50)
    description: str = Field(..., min_length=1, max_length=300)
    quantity: int = Field(default=1, ge=1)
    unit_price: float = Field(..., gt=0)


class TransactionIn(BaseModel):
    hospital_id: str = Field(..., min_length=1, max_length=20)
    transaction_id: str = Field(..., min_length=1, max_length=100)
    patient_reference: str = Field(..., min_length=1, max_length=100)
    items: list[TransactionItemIn] = Field(..., min_length=1)


# ── Transaction Response ──────────────────────────────────────────────────────

class BenchmarkResultOut(BaseModel):
    benchmark_price: Optional[float]
    submitted_price: float
    allowed_maximum: Optional[float]
    variance_percent: Optional[float]
    status: str


class TransactionItemOut(BaseModel):
    id: int
    hospital_code: str
    common_code: Optional[str]
    description: str
    quantity: int
    unit_price: float
    benchmark_price: Optional[float]
    benchmark_status: Optional[str]
    mapping_status: Optional[str]
    mapping_confidence: Optional[float]
    allowed_maximum: Optional[float]
    variance_percent: Optional[float]

    model_config = {"from_attributes": True}


class FWAResultOut(BaseModel):
    id: int
    rule_code: str
    rule_name: str
    result: str
    reason: Optional[str]
    severity: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class AdjudicationOut(BaseModel):
    id: int
    status: str
    approved_amount: float
    reason: Optional[str]
    reference: Optional[str]
    his_delivery_status: Optional[str]
    processed_at: datetime

    model_config = {"from_attributes": True}


class IntegrationEventOut(BaseModel):
    id: int
    event_type: str
    source: Optional[str]
    status: Optional[str]
    payload: Optional[Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class TransactionOut(BaseModel):
    id: int
    transaction_id: str
    hospital: HospitalOut
    patient_reference: str
    submitted_amount: float
    normalized_amount: float
    status: str
    created_at: datetime
    updated_at: datetime
    items: list[TransactionItemOut] = []
    fwa_results: list[FWAResultOut] = []
    adjudication: Optional[AdjudicationOut] = None
    integration_events: list[IntegrationEventOut] = []

    model_config = {"from_attributes": True}


class TransactionListItem(BaseModel):
    id: int
    transaction_id: str
    hospital_name: str
    hospital_code: str
    patient_reference: str
    submitted_amount: float
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── TPA ───────────────────────────────────────────────────────────────────────

class TPAItemIn(BaseModel):
    common_code: str
    description: str
    quantity: int
    submitted_amount: float
    allowed_amount: float


class TPAClaimIn(BaseModel):
    transaction_id: str
    member_id: str
    items: list[TPAItemIn]
    fwa_status: str
    fwa_flags: list[str] = []


class TPAResponse(BaseModel):
    transaction_id: str
    status: str
    approved_amount: float
    reason: Optional[str] = None
    reference: str


class HISCallbackIn(BaseModel):
    transaction_id: str
    facility_code: str
    status: str
    decision: str
    reason_code: Optional[str] = None
    reason: Optional[str] = None
    approved_amount: float
    timestamp: datetime


class HISCallbackOut(BaseModel):
    status: str
    message: str


# ── Dashboard ─────────────────────────────────────────────────────────────────

class DashboardMetrics(BaseModel):
    connected_hospitals: int
    total_transactions: int
    approved: int
    review: int
    fwa_flagged: int
    rejected: int


# ── Error ─────────────────────────────────────────────────────────────────────

class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Optional[Any] = None
