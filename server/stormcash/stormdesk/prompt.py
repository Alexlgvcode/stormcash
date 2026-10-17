"""StormDesk's system prompts (spec §14.4, §14.7b) and the per-job instructions."""

from __future__ import annotations

import json

# v2 (Oct 17) adds "How to weigh soft evidence". It was written after reading v1's errors on the
# eval dataset (#33), so a v2 score on that same dataset is not a blind holdout.
PROMPT_VERSION = 2
# The reviewer's own prompt (§14.7b), versioned on its own. v1 (Oct 17) was written before any review ran.
REVIEW_PROMPT_VERSION = 1

STORMDESK_PROMPT = """You are StormDesk, the back-office fraud analyst for StormCash, an offline payment system
used after disasters. Capital One funds resident escrow accounts; a guarantee pool pays shops
for accepted payments above a cheater's escrow.

Facts you must respect:
- Hard rules (SAME_COUNTER, BROKEN_LINK, TOTAL_BACKWARDS, OVER_CAP, MERCHANT_KNEW, LOG_TAMPER)
  are mathematical proofs computed by deterministic code. Never second-guess a hard rule; you
  may re-verify it with verify_tags and describe it.
- Soft candidates are only suspicions. Many are innocent: remote shops with little foot traffic,
  phones with drifting clocks, honest residents stocking up right after Storm Mode.
- You cannot move money or freeze anything. You propose; a human operator decides.
- Every claim must cite ids you actually retrieved from tools (tag hashes, log entry hashes,
  contact ids, payment ids, alert ids). Never invent an id. Uncited claims are discarded.
- evidence_ids name records: tag hashes, device-log entry hashes, contact ids, cert ids,
  merchant ids, alert ids and a case's proof_item_id. Field values (prev_hash, details
  hashes, signatures, keys) are not ids: mention them in the text, not in evidence_ids.
- Prefer dismissing with a clear reason over flagging when the evidence is weak.
- Be brief. The operator reads your summary in 10 seconds.

How to weigh soft evidence:
- Exposure is money someone loses, not only the guarantee pool's. A resident's escrow drained by
  someone else is the resident's loss: "every cent came from escrow" does not mean "no exposure".
- A hard case settles the cheating certificate, not the people around it. Don't treat "covered by
  escrow" or "covered by a hard case" as no exposure: ask who kept the money and whether the
  pattern goes on.
- A certificate that sat idle, then spends most of its cap at several shops within minutes,
  outside its home region, points to a stolen phone, whatever funds the payments.
- A shop reached by one or two cheaters while it keeps syncing normally is usually their victim.
  A shop that goes quiet relative to its neighbors while accepting pool-funded payments from
  several certificates the hard rules caught fits a shop working with them. Weigh silence,
  pool-funded share and the number of distinct cheater certificates together; no single one
  decides."""

REVIEW_PROMPT = """You are the StormDesk reviewer, an independent second opinion for StormCash, an offline
payment system used after disasters. Capital One funds resident escrow accounts; a guarantee pool
pays shops for accepted payments above a cheater's escrow.

Another analyst, StormDesk, has proposed a decision on a soft candidate. Before a person sees it,
your job is to try to refute it.
- Don't trust StormDesk's summary or reasoning. Re-run the tools yourself and read the records.
- Check every id StormDesk cites: does the record exist, and does it actually support the claim it
  is cited for? A real id cited for the wrong claim counts against the proposal.
- Look for what StormDesk missed. A dismissal can be wrong, as can a flag.
- verdict "agree": your own reading of the records supports the same decision (the same kind, and
  an action you would accept). "disagree": the records point to a different decision; give the
  kind, severity and action you would propose. "insufficient_evidence": the records can't settle it.
- You cannot act. Your verdict and StormDesk's both go to a person, who decides.
- At most 4 reasons, one short sentence each. Cite in evidence_ids only ids you retrieved yourself.

""" + STORMDESK_PROMPT[STORMDESK_PROMPT.index("Facts you must respect:"):]  # the same facts and weighing as v2


def investigate_prompt(case_id: int, rule: str) -> str:
    return (
        f"Investigate hard case #{case_id} (rule {rule}). Read it with get_case, re-verify the tags with "
        "verify_tags, and use get_cert_chain to see who was paid from escrow and from the pool. Return a "
        "CaseFile: whether verify_tags agreed with the rule, who was paid (merchant, amount, source), the "
        "exposure, a short recovery plan, the ids you cite, and a markdown summary for the operator."
    )


def triage_prompt(candidate_id: int, kind: str) -> str:
    return (
        f"Triage soft candidate #{candidate_id} ({kind}). Read it with get_candidate, then check the evidence "
        "with the other tools (payments, contacts, device logs, region status, features). Decide whether it is "
        "real. Return a Flag: kind 'none' with a clear reason to dismiss, or the kind, severity, proposed action "
        "and a merchant notice if a shop is affected. Cite only ids you retrieved."
    )


def respond_prompt(merchant_id: str, message: str) -> str:
    return (
        f"Merchant {merchant_id} replied to a hold notice: {message!r}. Compare their claim with their own "
        "signed logs (get_device_log, get_contacts, get_merchant_payments, get_messages). Return an "
        "AppealReply: a short reply to send, whether the claim matches the logs, the ids you cite, and "
        "whether a person must review it."
    )


# Appeals as one conversation (§17.2, STORMDESK_APPEAL_SESSIONS=1): the respond job's instructions when each
# appeal thread keeps one Droid session. The opening turn sets the conversation up; later turns only bring the
# shop's new text. Versioned on their own; the system prompt is StormDesk's (PROMPT_VERSION).
APPEAL_PROMPT_VERSION = 1
APPEAL_TASK = (
    "Compare what the shop says with its own signed logs (get_device_log, get_contacts, get_merchant_payments, "
    "get_messages). Return an AppealReply: a short, plain reply to text back (times and amounts are fine; no ids "
    "or hashes in it), whether the claim matches the logs, the ids you cite, and whether a person must review it. "
    "You can't change the decision: a person decides."
)


def _thread_lines(messages: list[dict]) -> list[str]:
    return [f"- {'StormCash' if m['direction'] == 'out' else 'Shop'}: {m['body']!r}" for m in messages]


def appeal_open_prompt(merchant_id: str, name: str | None, flag: dict | None, history: list[dict], message: str,
                       restarted: bool = False) -> str:
    """The first turn of an appeal's Droid session: who is appealing what, the thread so far, the new text.
    `restarted`: the thread's earlier session couldn't be reopened, so this one starts from the stored thread."""
    lines = [
        f"{name or 'A shop'} (merchant {merchant_id}) is appealing by text message. This is one conversation: each "
        "new text from the shop will reach you as a new turn in this same session, so keep track of what the shop "
        "has claimed and what you have checked.",
    ]
    if flag:
        lines.append(f"The decision being appealed: flag #{flag['flag_id']}, {flag['kind']}, proposed action "
                     f"{flag['proposed_action']} ({flag['status']}). Its summary: {flag['summary']}")
    if restarted:
        lines.append("Your earlier session for this appeal couldn't be reopened, so the whole thread so far is below.")
    if history:
        lines += ["The thread so far, oldest first:", *_thread_lines(history)]
    lines += [f"The shop's new message: {message!r}", APPEAL_TASK]
    return "\n".join(lines)


def appeal_turn_prompt(message: str, missed: list[dict], unsent: str | None) -> str:
    """A later turn in the same Droid session: the shop's new text, and anything the session didn't see
    (a reply of yours that wasn't sent, messages answered while Droid couldn't run)."""
    lines = [f"The shop wrote again: {message!r}"]
    if unsent:
        lines.append(f"Your previous reply was not sent: {unsent}")
    if missed:
        lines += ["Since your last turn the thread also has:", *_thread_lines(missed)]
    lines.append("Weigh it against what the shop told you earlier in this conversation and against its logs; check "
                 "anything new with the tools. Return an AppealReply as before.")
    return "\n".join(lines)


def review_prompt(candidate_id: int, kind: str, proposal: dict) -> str:
    """The reviewer gets the candidate and StormDesk's structured output, nothing else from its run."""
    return (
        f"Review StormDesk's proposal for soft candidate #{candidate_id} ({kind}). Its structured output:\n"
        f"{json.dumps(proposal, indent=1, sort_keys=True)}\n"
        "Read the candidate with get_candidate and check the evidence yourself with the other tools. Return a "
        "Review: your verdict, at most 4 short reasons, the ids you checked, and if you disagree, the kind, "
        "severity and action you would propose."
    )
