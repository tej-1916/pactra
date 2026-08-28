"""FastAPI application bootstrap."""

from __future__ import annotations

from fastapi import FastAPI

from apps.api.pactra.api.routes_missions import router as missions_router
from apps.api.pactra.api.routes_payments import router as payments_router
from apps.api.pactra.api.routes_risk import router as risk_router
from apps.api.pactra.config import get_settings

app = FastAPI(title="PACTRA API", version="0.1.0")
app.include_router(missions_router)
app.include_router(payments_router)
app.include_router(risk_router)


@app.get("/health")
async def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "app_env": settings.app_env,
        "payment_test_mode": settings.payment_test_mode,
    }
