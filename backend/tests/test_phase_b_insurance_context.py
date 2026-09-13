import pytest
from app.models import Transaction, Claim, Member, CommercialPolicy, Patient
from app.services.transaction_orchestrator import process_transaction
from app.schemas import TransactionIn, TransactionItemIn

@pytest.mark.anyio
async def test_unknown_insurance_context(seeded_client):
    client, db_session, h_a, h_b, auth_a, auth_b = seeded_client

    payload = TransactionIn(
        transaction_id="TXN-UNKNOWN-1",
        hospital_id=h_a.hospital_code,
        patient_reference="UNKNOWN-PATIENT-999",
        items=[
            TransactionItemIn(
                hospital_code="TEST-CODE-A",
                description="Consultation",
                quantity=1,
                unit_price=150.0
            )
        ]
    )

    txn = await process_transaction(payload, db_session)

    assert txn.transaction_id == "TXN-UNKNOWN-1"
    
    claim = db_session.query(Claim).filter(Claim.transaction_id == txn.id).first()
    assert claim is not None
    assert claim.status == "PENDING_ELIGIBILITY"

    member = db_session.query(Member).filter(Member.id == claim.member_id).first()
    assert member is None
    policy = db_session.query(CommercialPolicy).filter(CommercialPolicy.id == claim.policy_id).first()
    assert policy is None

    assert txn.status == "PENDING_ELIGIBILITY"

@pytest.mark.anyio
async def test_duplicate_transaction_idempotency(seeded_client):
    client, db_session, h_a, h_b, auth_a, auth_b = seeded_client

    payload = TransactionIn(
        transaction_id="TXN-IDEM-1",
        hospital_id=h_a.hospital_code,
        patient_reference="PAT-INT-001",
        items=[
            TransactionItemIn(
                hospital_code="TEST-CODE-A",
                description="Consultation",
                quantity=1,
                unit_price=100.0
            )
        ]
    )

    txn1 = await process_transaction(payload, db_session)
    assert txn1 is not None

    txn2 = await process_transaction(payload, db_session)
    assert txn1.id == txn2.id
    
    claims = db_session.query(Claim).filter(Claim.transaction_id == txn1.id).all()
    assert len(claims) == 1

@pytest.mark.anyio
async def test_decimal_precision(seeded_client):
    client, db_session, h_a, h_b, auth_a, auth_b = seeded_client

    payload = TransactionIn(
        transaction_id="TXN-DECIMAL-1",
        hospital_id=h_a.hospital_code,
        patient_reference="PAT-INT-001",
        items=[
            TransactionItemIn(
                hospital_code="TEST-CODE-A",
                description="Consultation",
                quantity=1,
                unit_price=100.55
            )
        ]
    )

    txn = await process_transaction(payload, db_session)
    claim = db_session.query(Claim).filter(Claim.transaction_id == txn.id).first()

    from decimal import Decimal
    assert claim.total_billed_amount == Decimal("100.55")

