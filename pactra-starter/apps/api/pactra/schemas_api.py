"""API response shapes (read models)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class OfferOut(BaseModel):
    offer_id: uuid.UUID
    merchant_id: str
    merchant_name: str
    merchant_trust: float
    product_id: str
    title: str
    amount_inr: int
    currency: str
    rating: float
    in_stock: bool
    valid: bool
    rejection_reasons: list[str]
    rank: int | None


class PolicyDecisionOut(BaseModel):
    decision: str
    reason_codes: list[str]
    requested_amount: int | None
    soft_budget: int
    hard_limit: int
    selected_offer_id: uuid.UUID | None


class AuditEventOut(BaseModel):
    event_id: uuid.UUID
    sequence: int
    event_type: str
    actor: str
    payload: dict
    previous_hash: str
    event_hash: str
    created_at: datetime


class MissionOut(BaseModel):
    id: uuid.UUID
    state: str
    raw_query: str | None
    quantity: int
    offers: list[OfferOut]
    policy_decision: PolicyDecisionOut | None
    created_at: datetime
