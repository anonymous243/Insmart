"""
CodeMappingService
Resolves hospital-specific codes to central common codes.
"""
import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Hospital, HospitalCode, CodeMapping, CommonCode

logger = logging.getLogger(__name__)


@dataclass
class MappingResult:
    hospital_code: str
    common_code: Optional[str]
    common_description: Optional[str]
    confidence: float
    mapping_status: str  # MAPPED | UNMAPPED


class CodeMappingService:
    def __init__(self, db: Session):
        self.db = db

    def resolve(self, hospital_db_id: int, hospital_code: str) -> MappingResult:
        """
        Resolve a hospital-specific code to a common code.
        Returns MappingResult with status MAPPED or UNMAPPED.
        """
        hc = (
            self.db.query(HospitalCode)
            .filter(
                HospitalCode.hospital_id == hospital_db_id,
                HospitalCode.hospital_code == hospital_code,
                HospitalCode.active == True,
            )
            .first()
        )

        if hc is None:
            logger.warning(
                "No hospital_code record found: hospital_id=%s code=%s",
                hospital_db_id,
                hospital_code,
            )
            return MappingResult(
                hospital_code=hospital_code,
                common_code=None,
                common_description=None,
                confidence=0.0,
                mapping_status="UNMAPPED",
            )

        mapping = (
            self.db.query(CodeMapping)
            .filter(
                CodeMapping.hospital_id == hospital_db_id,
                CodeMapping.hospital_code_id == hc.id,
                CodeMapping.mapping_status == "MAPPED",
            )
            .first()
        )

        if mapping is None:
            logger.warning(
                "No code mapping found: hospital_id=%s code=%s",
                hospital_db_id,
                hospital_code,
            )
            return MappingResult(
                hospital_code=hospital_code,
                common_code=None,
                common_description=None,
                confidence=0.0,
                mapping_status="UNMAPPED",
            )

        cc: CommonCode = mapping.common_code_obj
        logger.info(
            "Code mapped: %s → %s (confidence=%.2f)",
            hospital_code,
            cc.common_code,
            mapping.confidence,
        )
        return MappingResult(
            hospital_code=hospital_code,
            common_code=cc.common_code,
            common_description=cc.description,
            confidence=mapping.confidence,
            mapping_status="MAPPED",
        )
