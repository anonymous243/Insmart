from abc import ABC, abstractmethod
from typing import Any
from sqlalchemy.orm import Session
from app.models import Hospital
from app.schemas import TransactionIn

class BaseAdapter(ABC):
    @abstractmethod
    def parse_payload(self, raw_payload: Any, hospital: Hospital, db: Session) -> TransactionIn:
        """
        Parses an external HIS payload into the canonical internal TransactionIn schema.
        Should raise a ValueError if the payload is invalid.
        """
        pass
