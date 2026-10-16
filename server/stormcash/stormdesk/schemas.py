"""Structured outputs (spec §14.5)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Flag(BaseModel):
    kind: Literal["merchant_silence", "cap_drain", "region_dark", "none"]
    severity: Literal["info", "review", "urgent"]
    subject_id: str
    evidence_ids: list[str]  # must exist; the server checks (§14.7)
    exposure_cents: int = Field(ge=0)
    summary: str  # ≤ 2 sentences, operator-facing
    reasoning: str  # ≤ 6 bullet points, shown on expand
    proposed_action: Literal["none", "lower_merchant_limit", "hold_pool_payout", "freeze_cert", "dispatch_relay"]
    action_params: dict[str, int | str] = Field(default_factory=dict)  # e.g. {"limit_cents": 1000}
    merchant_notice: str | None = None  # draft text for Photon, if the action affects a merchant


class CaseFile(BaseModel):
    rule: str
    verified_independently: bool  # verify_tags agreed with the hard rule
    who_paid: list[dict]  # merchant, amount, source (escrow/pool)
    exposure_cents: int = Field(ge=0)
    recovery_plan: list[str]
    evidence_ids: list[str]
    summary_md: str


class AppealReply(BaseModel):
    reply: str  # sent to the merchant
    claim_consistent_with_logs: bool
    evidence_ids: list[str]
    escalate: bool
