"""
Healthcare Claims Processing Platform — Central API Hub
FastAPI application entry point.
"""
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

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Healthcare Claims Platform API...")
    logger.info("Database connection established.")
    yield
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

app.include_router(api_router)


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok", "service": "Healthcare Claims Platform"}
