from typing import Any
from sqlalchemy.orm import Session
from app.models import Hospital
from app.schemas import TransactionIn, TransactionItemIn
from app.services.integrations.base_adapter import BaseAdapter

class RESTAdapter(BaseAdapter):
    def parse_payload(self, raw_payload: Any, hospital: Hospital, db: Session) -> TransactionIn:
        """
        Parses a REST API JSON payload into the canonical internal TransactionIn schema.
        Expected format:
        {
          "claim_reference": "HIS-AP-001",
          "patient_ref": "PAT-DEMO-100",
          "services": [
            {
              "service_code": "AP-CT-001",
              "description": "CT Scan Head",
              "quantity": 1,
              "amount": 2500000
            }
          ]
        }
        """
        if not isinstance(raw_payload, dict):
            raise ValueError("Payload must be a JSON object")

        claim_reference = raw_payload.get("claim_reference")
        patient_ref = raw_payload.get("patient_ref")
        services = raw_payload.get("services", [])

        if not claim_reference or not patient_ref:
            raise ValueError("Missing 'claim_reference' or 'patient_ref'")
        if not isinstance(services, list) or not services:
            raise ValueError("'services' must be a non-empty list")

        items = []
        for svc in services:
            service_code = svc.get("service_code")
            description = svc.get("description")
            quantity = svc.get("quantity", 1)
            amount = svc.get("amount")

            if not service_code or not description or amount is None:
                raise ValueError("Each service must contain 'service_code', 'description', and 'amount'")

            try:
                quantity = int(quantity)
                amount = float(amount)
            except ValueError:
                raise ValueError("Invalid numeric value for 'quantity' or 'amount'")

            items.append(TransactionItemIn(
                hospital_code=service_code,
                description=description,
                quantity=quantity,
                unit_price=amount
            ))

        return TransactionIn(
            hospital_id=hospital.hospital_code,
            transaction_id=claim_reference,
            patient_reference=patient_ref,
            items=items
        )
