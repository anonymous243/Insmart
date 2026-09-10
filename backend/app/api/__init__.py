from fastapi import APIRouter
from app.api.v1 import (
    routes_transactions,
    routes_tpa,
    routes_hospitals,
    routes_codes,
    routes_demo,
    routes_audit,
    routes_auth,
    routes_facility,
    routes_integrations,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(routes_auth.router)
api_router.include_router(routes_facility.router)
api_router.include_router(routes_transactions.router)
api_router.include_router(routes_tpa.router)
api_router.include_router(routes_hospitals.router)
api_router.include_router(routes_codes.router)
api_router.include_router(routes_demo.router)
api_router.include_router(routes_audit.router)
api_router.include_router(routes_integrations.router)
