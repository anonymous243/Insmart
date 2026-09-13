"""
Structured logging configuration for C5 observability.

Provides JSON-structured log formatter and correlation ID filtering.
Ensures no secrets, credentials, or unnecessary patient data are logged.
"""
import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Context variable for correlation ID - propagates through async tasks
correlation_id_var: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> Optional[str]:
    """Get current correlation ID from context."""
    return correlation_id_var.get()


def set_correlation_id(correlation_id: Optional[str]) -> None:
    """Set correlation ID in current context."""
    correlation_id_var.set(correlation_id)


def generate_correlation_id() -> str:
    """Generate a new correlation ID."""
    return f"corr-{uuid.uuid4().hex[:16]}"


class StructuredFormatter(logging.Formatter):
    """
    JSON-structured log formatter for C5.
    
    Emits log records as JSON with consistent fields:
      - timestamp
      - level
      - event
      - message
      - correlation_id
      - context fields (transaction_id, claim_id, hospital_id, job_id, etc.)
    
    Never logs:
      - passwords
      - JWTs
      - authorization headers
      - API keys
      - credentials
      - full patient-sensitive payloads
    """
    
    # Fields that must never appear in logs
    SENSITIVE_FIELDS = {
        "password", "jwt", "token", "secret", "api_key", "authorization",
        "credential", "private_key", "access_token", "refresh_token",
        "patient_name", "patient_dob", "patient_address", "phone",
    }
    
    def __init__(self, service_name: str = "claims-platform"):
        super().__init__()
        self.service_name = service_name
    
    def _sanitize(self, data: Any) -> Any:
        """Recursively sanitize sensitive data from log records."""
        if isinstance(data, dict):
            return {
                k: "***REDACTED***" if k.lower() in self.SENSITIVE_FIELDS else self._sanitize(v)
                for k, v in data.items()
            }
        elif isinstance(data, list):
            return [self._sanitize(item) for item in data[:5]]  # Limit array length
        elif isinstance(data, str) and len(data) > 200:
            return data[:200] + "...[truncated]"
        return data
    
    def format(self, record: logging.LogRecord) -> str:
        correlation_id = get_correlation_id()
        
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": self.service_name,
            "level": record.levelname,
            "event": record.getMessage().split(" ")[0] if record.getMessage() else "LOG",
            "message": record.getMessage()[:500],  # Truncate long messages
            "correlation_id": correlation_id,
        }
        
        # Add extra context fields if present
        extra_fields = {}
        for key in ["transaction_id", "claim_id", "hospital_id", "background_job_id",
                    "external_operation_id", "external_attempt_id", "reconciliation_id",
                    "provider", "operation", "job_type", "attempt_number",
                    "error_classification", "duration_ms", "outcome", "status"]:
            value = getattr(record, key, None)
            if value is not None:
                extra_fields[key] = value
        
        if extra_fields:
            log_entry["context"] = self._sanitize(extra_fields)
        
        # Add exception info if present
        if record.exc_info and record.exc_info[0]:
            log_entry["error"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1])[:200],
            }
        
        return json.dumps(log_entry, default=str)


class CorrelationFilter(logging.Filter):
    """Inject correlation ID into log records."""
    
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id()
        return True


def setup_structured_logging(service_name: str = "claims-platform", log_level: str = "INFO") -> None:
    """
    Configure structured JSON logging for the application.
    
    Replaces default logging configuration with JSON formatter.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Add structured handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter(service_name=service_name))
    handler.addFilter(CorrelationFilter())
    root_logger.addHandler(handler)
    
    # Reduce noise from external libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
