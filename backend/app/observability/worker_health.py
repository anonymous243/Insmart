"""
C5 Worker Health Tracking

Tracks worker process health independently from FastAPI application health.

Worker states:
- STARTING: Worker is initializing
- RUNNING: Worker is actively polling and processing jobs
- STOPPING: Worker is shutting down gracefully
- STOPPED: Worker has stopped
- UNHEALTHY: Worker heartbeat is stale
"""
import time
import threading
from datetime import datetime, timezone
from typing import Optional, Dict, Any


class WorkerHealth:
    """
    Thread-safe worker health tracker.
    
    Updated by the worker loop itself. Read by operational endpoints.
    """
    
    def __init__(self):
        self._lock = threading.Lock()
        self._state: str = "STOPPED"
        self._started_at: Optional[datetime] = None
        self._last_poll_at: Optional[datetime] = None
        self._last_job_completed_at: Optional[datetime] = None
        self._jobs_processed: int = 0
        self._jobs_failed: int = 0
        self._lease_recoveries: int = 0
        self._errors: list = []
        self._worker_id: Optional[str] = None
    
    def set_starting(self, worker_id: str) -> None:
        with self._lock:
            self._state = "STARTING"
            self._worker_id = worker_id
    
    def set_running(self) -> None:
        with self._lock:
            self._state = "RUNNING"
            if not self._started_at:
                self._started_at = datetime.now(timezone.utc)
    
    def set_stopping(self) -> None:
        with self._lock:
            self._state = "STOPPING"
    
    def set_stopped(self) -> None:
        with self._lock:
            self._state = "STOPPED"
    
    def record_poll(self) -> None:
        with self._lock:
            self._last_poll_at = datetime.now(timezone.utc)
    
    def record_job_completed(self, success: bool = True) -> None:
        with self._lock:
            self._last_job_completed_at = datetime.now(timezone.utc)
            if success:
                self._jobs_processed += 1
            else:
                self._jobs_failed += 1
    
    def record_lease_recovery(self) -> None:
        with self._lock:
            self._lease_recoveries += 1
    
    def record_error(self, error: str) -> None:
        with self._lock:
            self._errors.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": str(error)[:200],
            })
            # Keep only last 50 errors
            if len(self._errors) > 50:
                self._errors = self._errors[-50:]
    
    def get_health(self) -> Dict[str, Any]:
        """
        Get worker health status.
        
        Returns:
        - state: STARTING, RUNNING, STOPPING, STOPPED, UNHEALTHY
        - worker_id
        - started_at
        - last_poll_at
        - last_job_completed_at
        - jobs_processed
        - jobs_failed
        - lease_recoveries
        - recent_errors
        - healthy: boolean
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            
            # Determine if worker is healthy
            healthy = False
            if self._state == "RUNNING":
                # Worker is healthy if it polled within last 60 seconds
                if self._last_poll_at and (now - self._last_poll_at).total_seconds() < 60:
                    healthy = True
                else:
                    self._state = "UNHEALTHY"
            
            return {
                "state": self._state,
                "worker_id": self._worker_id,
                "healthy": healthy,
                "started_at": self._started_at.isoformat() if self._started_at else None,
                "last_poll_at": self._last_poll_at.isoformat() if self._last_poll_at else None,
                "last_job_completed_at": self._last_job_completed_at.isoformat() if self._last_job_completed_at else None,
                "jobs_processed": self._jobs_processed,
                "jobs_failed": self._jobs_failed,
                "lease_recoveries": self._lease_recoveries,
                "recent_errors": self._errors[-5:],  # Last 5 errors
            }


# Global worker health instance
worker_health = WorkerHealth()
