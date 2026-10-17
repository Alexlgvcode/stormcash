"""Structured outputs (spec §14.5, §14.7b)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Kind = Literal["merchant_silence", "cap_drain", "region_dark", "none"]
Severity = Literal["info", "review", "urgent"]
Action = Literal["none", "lower_merchant_limit", "hold_pool_payout", "freeze_cert", "dispatch_relay"]


class Flag(BaseModel):
    kind: Kind
    severity: Severity
    subject_id: str
    evidence_ids: list[str]  # must exist; the server checks (§14.7)
    exposure_cents: int = Field(ge=0)
    summary: str  # ≤ 2 sentences, operator-facing
    reasoning: str  # ≤ 6 bullet points, shown on expand
    proposed_action: Action
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


class Review(BaseModel):  # the reviewer's output (§14.7b); the docstring is part of the schema Droid sees
    """Your second opinion on StormDesk's proposal. You never act: a person reads both views and decides."""

    verdict: Literal["agree", "disagree", "insufficient_evidence"]
    reasons: list[str] = Field(json_schema_extra={"maxItems": 4})  # ≤ 4 short bullets, shown to the operator
    evidence_ids: list[str]  # the records the reviewer read itself; the server checks them (§14.7)
    suggested_kind: Kind | None = None  # when it disagrees: what it would propose instead
    suggested_severity: Severity | None = None
    suggested_action: Action | None = None

    @field_validator("reasons")
    @classmethod
    def _at_most_four(cls, reasons: list[str]) -> list[str]:
        return reasons[:4]  # asked for ≤ 4; a fifth bullet isn't worth failing the run over
