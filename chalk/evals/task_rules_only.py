"""The rules-only baseline as a Chalk task (spec §13): flag every candidate with its default action.

Deterministic and self-contained (Chalk ships this one file). It reads no
evidence, so it cites nothing and citations-valid scores it n/a.
"""

import json

import chalkcompute

DEFAULT_ACTIONS = {"merchant_silence": "hold_pool_payout", "cap_drain": "freeze_cert", "region_dark": "dispatch_relay"}


def rules_only_flag(kind: str, subject_id: str, features: dict) -> dict:
    exposure = {"merchant_silence": features.get("pool_funded_cents"),
                "cap_drain": features.get("spent_15m_cents")}.get(kind) or 0
    return {
        "kind": kind,
        "severity": "review",
        "subject_id": subject_id,
        "evidence_ids": [],
        "exposure_cents": int(exposure),
        "summary": f"Rules-only baseline: every {kind} candidate gets its default action.",
        "reasoning": "- Rules-only baseline (spec §13): flag every candidate with its default action.\n"
                     "- No evidence was read.",
        "proposed_action": DEFAULT_ACTIONS[kind],
        "action_params": {},
        "merchant_notice": None,
        "_run": {"runner": "rules_only", "citations_valid": None},
    }


@chalkcompute.function(name="sd-rules-only", concurrency=8)
def rules_only(kind: str, subject_id: str, features: str) -> str:
    return json.dumps(rules_only_flag(kind, subject_id, json.loads(features)), sort_keys=True)
