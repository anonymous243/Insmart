"""
Healthcare Claims Processing Platform — Central API Hub
FastAPI application entry point.
"""
import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.base import Base
import app.db.session as _db_session  # import module, not names, so tests can patch
from app.api import api_router

# Import all models so SQLAlchemy creates tables
import app.models  # noqa: F401

# ── Observability ──────────────────────────────────────────────────────────────
from app.observability.logging import setup_structured_logging, get_correlation_id, set_correlation_id, generate_correlation_id
from app.observability.worker_health import worker_health

setup_structured_logging(service_name="claims-platform", log_level=settings.LOG_LEVEL)
logger = logging.getLogger(__name__)


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Healthcare Claims Platform API...")
    logger.info("Database connection established.")

    # ── C3: Start background job worker ──────────────────────────────────────
    from app.workers.job_worker import run_worker_loop
    from app.db.session import SessionLocal
    import app.workers.job_worker as _jw
    _jw.shutdown_event = asyncio.Event()
    worker_task = asyncio.create_task(
        run_worker_loop(SessionLocal, _jw.shutdown_event),
        name="c3-job-worker",
    )
    logger.info("C3: Background job worker started.")

    yield

    # ── C3: Graceful shutdown ─────────────────────────────────────────────────
    logger.info("C3: Signalling worker shutdown...")
    _jw.shutdown_event.set()
    try:
        await asyncio.wait_for(worker_task, timeout=30.0)
        logger.info("C3: Worker stopped cleanly.")
    except asyncio.TimeoutError:
        logger.warning("C3: Worker did not stop within 30s — cancelling.")
        worker_task.cancel()
    except asyncio.CancelledError:
        pass

    logger.info("Shutting down.")



# ── Application ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Healthcare Claims Processing Platform",
    description=(
        "Central API Hub for healthcare claim integration, normalization, "
        "FWA detection, TPA routing, and adjudication. "
        "Hospitals submit claims via their existing HIS — no portal login required."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.observability.metrics import metrics as _metrics_collector
from starlette.middleware.base import BaseHTTPMiddleware
import time

class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """Inject correlation ID into each request and response."""
    async def dispatch(self, request, call_next):
        cid = request.headers.get("X-Correlation-ID") or generate_correlation_id()
        set_correlation_id(cid)
        request.state.correlation_id = cid
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            set_correlation_id(None)
        duration_ms = (time.perf_counter() - start) * 1000.0
        _metrics_collector.record_histogram(
            "http_request_duration_seconds",
            duration_ms / 1000.0,
            labels={"method": request.method, "path": request.url.path, "status": str(response.status_code)},
        )
        _metrics_collector.increment_counter(
            "http_requests_total",
            labels={"method": request.method, "path": request.url.path, "status": str(response.status_code)},
        )
        response.headers["X-Correlation-ID"] = cid
        return response

app.add_middleware(CorrelationIDMiddleware)

app.include_router(api_router)


# ── Health & Observability Endpoints ─────────────────────────────────────────

@app.get("/health", tags=["Health"])
def health():
    """Liveness: application process is running."""
    return {"status": "ok", "service": "Healthcare Claims Platform"}


@app.get("/health/ready", tags=["Health"])
def readiness():
    """Readiness: database connectivity and worker health."""
    from app.db.session import SessionLocal
    from app.observability.worker_health import worker_health
    
    db_ok = False
    try:
        db = SessionLocal()
        db.execute("SELECT 1")
        db.close()
        db_ok = True
    except Exception:
        pass
    
    health = worker_health.get_health()
    ready = db_ok and health["healthy"]
    
    return {
        "ready": ready,
        "database": db_ok,
        "worker": health,
    }


@app.get("/health/live", tags=["Health"])
def liveness():
    """Liveness: process is alive."""
    return {"status": "alive"}


@app.get("/metrics", tags=["Observability"])
def metrics_endpoint():
    """Expose application metrics."""
    return _metrics_collector.get_all_metrics()

