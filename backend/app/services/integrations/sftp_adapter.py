from typing import Any
from sqlalchemy.orm import Session
from app.models import Hospital
from app.schemas import TransactionIn
from app.services.integrations.base_adapter import BaseAdapter

class SFTPAdapter(BaseAdapter):
    def parse_payload(self, raw_payload: Any, hospital: Hospital, db: Session) -> TransactionIn:
        """
        Placeholder for SFTP-based integrations.
        Architecture-ready but not operational.
        """
        raise NotImplementedError("SFTP integration not operational in this version.")
