"""Offline checks and hard fraud rules (spec §8.2, §8.3, §9.4, §9.5).

Pure functions over already-decoded objects: no DB, no clock, no I/O. Callers
pass `now` explicitly. Inputs other than the PAY under test are assumed to be
verified already (stored tags, policy, device logs).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .objects import Dlog, Mcert, Pay, Policy, Proof, Req, Tag, dlog_genesis, genesis, id8

CLOCK_TOLERANCE_S = 600

SAME_COUNTER = "SAME_COUNTER"
BROKEN_LINK = "BROKEN_LINK"
TOTAL_BACKWARDS = "TOTAL_BACKWARDS"


# Single tags and pairs (§8.3) ----------------------------------------------------


def tag_valid(tag: Tag) -> bool:
    """Single-tag validity: counter >= 1, amount > 0, cum >= amount, and a
    counter-1 tag starts the chain (prev_hash = GENESIS, cum = amount)."""
    if tag.counter < 1 or tag.amount_cents <= 0 or tag.cum_cents < tag.amount_cents:
        return False
    if tag.counter == 1:
        return tag.prev_hash == genesis(tag.cert_id) and tag.cum_cents == tag.amount_cents
    return True


def _ordered(x: Tag, y: Tag) -> tuple[Tag, Tag]:
    """Order a pair so a.counter <= b.counter (ties by tag_hash)."""
    return (x, y) if (x.counter, x.tag_hash) <= (y.counter, y.tag_hash) else (y, x)


def rules_fired(x: Tag, y: Tag) -> list[str]:
    """Every equivocation rule the pair breaks, in rule order R1, R2, R3."""
    if x.cert_id != y.cert_id:
        return []
    a, b = _ordered(x, y)
    fired = []
    if a.counter == b.counter and a.tag_hash != b.tag_hash:
        fired.append(SAME_COUNTER)
    if b.counter == a.counter + 1 and b.prev_hash != a.tag_hash:
        fired.append(BROKEN_LINK)
    if b.counter > a.counter and b.cum_cents - b.amount_cents < a.cum_cents:
        fired.append(TOTAL_BACKWARDS)
    return fired


def equivocation(x: Tag, y: Tag) -> str | None:
    """The lowest-numbered rule (R1, R2, R3) the pair breaks, or None."""
    fired = rules_fired(x, y)
    return fired[0] if fired else None


def make_proof(x: Tag, y: Tag) -> Proof | None:
    rule = equivocation(x, y)
    if rule is None:
        return None
    a, b = _ordered(x, y)
    return Proof(a, b, rule)


def verify_proof(proof: Proof, holder_pub: bytes) -> bool:
    """A PROOF is valid if both tags are signed by holder_pub and break its rule."""
    return (
        proof.a.verify(holder_pub)
        and proof.b.verify(holder_pub)
        and proof.rule in rules_fired(proof.a, proof.b)
    )


# Merchant offline checks (§8.2) -------------------------------------------------


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    check: str | None = None  # "C1".."C6" on failure
    reason: str | None = None  # machine token, see §8.2
    rule: str | None = None  # equivocation rule when C6 found one
    conflict: Tag | None = None  # the stored tag it conflicts with

    @classmethod
    def fail(cls, check: str, reason: str, rule: str | None = None, conflict: Tag | None = None):
        return cls(False, check, reason, rule, conflict)


PASSED = CheckResult(True)


def merchant_check(
    pay: Pay,
    *,
    server_pub: bytes,
    merchant: Mcert,
    req: Req,
    policy: Policy | None,
    stored_tags: Iterable[Tag],
    now: int,
) -> CheckResult:
    """Run C1-C6 in order on a scanned PAY; the first failure wins.

    `merchant` is this shop's own MCERT, `req` the open request it showed,
    `policy` the highest verified POLICY (or None), `stored_tags` every
    verified tag this phone holds.
    """
    cert, tag, det = pay.cert, pay.tag, pay.det

    # C1: certificate issued by StormCash.
    if not cert.verify(server_pub):
        return CheckResult.fail("C1", "BAD_CERT_SIG")

    # C2: not expired (10-min clock tolerance) and not frozen.
    if now > cert.expires_at + CLOCK_TOLERANCE_S:
        return CheckResult.fail("C2", "EXPIRED")
    if policy is not None and cert.cert_id in policy.frozen_certs:
        return CheckResult.fail("C2", "FROZEN")

    # C3: the tag is for this certificate and signed by its holder.
    if tag.cert_id != cert.cert_id:
        return CheckResult.fail("C3", "WRONG_CERT")
    if not tag.verify(cert.holder_pub):
        return CheckResult.fail("C3", "BAD_TAG_SIG")

    # C4: the payment answers this shop's open request.
    if tag.details_hash != det.digest():
        return CheckResult.fail("C4", "DETAILS_MISMATCH")
    if det.merchant_pub != merchant.merchant_pub:
        return CheckResult.fail("C4", "WRONG_MERCHANT")
    if det.nonce != req.nonce:
        return CheckResult.fail("C4", "WRONG_NONCE")
    if tag.amount_cents != req.amount_cents:
        return CheckResult.fail("C4", "WRONG_AMOUNT")
    if now > req.req_expires_at:
        return CheckResult.fail("C4", "REQ_EXPIRED")

    # C5: amounts.
    if tag.amount_cents <= 0 or tag.cum_cents < tag.amount_cents:
        return CheckResult.fail("C5", "BAD_AMOUNT")
    if tag.cum_cents > cert.cap_cents:
        return CheckResult.fail("C5", "OVER_CAP")
    limit = policy.merchant_limit(merchant.merchant_id) if policy is not None else None
    if limit is not None and tag.amount_cents > limit:
        return CheckResult.fail("C5", "OVER_LIMIT")

    # C6: chain checks against every stored tag for this cert.
    if not tag_valid(tag):
        return CheckResult.fail("C6", "INVALID_TAG")
    same_cert = sorted(
        (s for s in stored_tags if s.cert_id == tag.cert_id),
        key=lambda s: (s.counter, s.tag_hash),
    )
    for stored in same_cert:
        rule = equivocation(stored, tag)
        if rule is not None:
            return CheckResult.fail("C6", rule, rule, stored)
    if same_cert and tag.counter <= max(s.counter for s in same_cert):
        return CheckResult.fail("C6", "COUNTER_NOT_NEW")

    return PASSED


# R4 OVER_CAP (§8.3, server) ------------------------------------------------------


def over_cap(settled_tags: Iterable[Tag], caps: Iterable[int]) -> bool:
    """R4: the highest settled cum exceeds the highest cap of any issued version."""
    caps = list(caps)
    if not caps:
        raise ValueError("over_cap needs the caps of the issued versions")
    cums = [t.cum_cents for t in settled_tags]
    return bool(cums) and max(cums) > max(caps)


# R5 MERCHANT_KNEW (§9.4, server) ---------------------------------------------------


@dataclass(frozen=True)
class MerchantKnew:
    clause: str  # "HELD_IDS" (a) or "PAIRED_CONTACT" (b)
    conflict: bytes  # tag_hash of the conflicting tag x
    contact_id: bytes | None = None  # set for clause (b)


def merchant_knew(
    z: Tag,
    *,
    merchant_pub: bytes,
    t_accept: int,
    cert_tags: Iterable[Tag],
    logs: Iterable[Dlog],
) -> MerchantKnew | None:
    """R5: did merchant M knowingly accept tag z?

    `cert_tags` are the tags the server holds for z's cert; `logs` are verified
    DLOG entries from any devices. A contact counts only when it is paired
    (both M and the peer logged the same contact_id naming each other), and it
    is dated by M's own CONTACT entry, so both times come from M's clock.
    """
    zh = z.tag_hash
    conflicts = sorted(
        (x for x in cert_tags if x.cert_id == z.cert_id and x.tag_hash != zh and equivocation(x, z)),
        key=lambda x: (x.counter, x.tag_hash),
    )
    if not conflicts:
        return None
    logs = list(logs)

    # (a) M's own ACCEPT entry for z lists x in held_ids.
    accepts = [
        e for e in logs
        if e.device_pub == merchant_pub and e.kind == "ACCEPT" and e.tag_hash == zh
    ]
    for x in conflicts:
        if any(x.tag_hash in e.held_ids for e in accepts):
            return MerchantKnew("HELD_IDS", x.tag_hash)

    # (b) a paired contact before t_accept in which x reached M.
    mine = {
        e.contact_id: e for e in logs
        if e.device_pub == merchant_pub and e.kind == "CONTACT"
    }
    pairs = []
    for peer in logs:
        if peer.kind != "CONTACT" or peer.peer_pub != merchant_pub:
            continue
        own = mine.get(peer.contact_id)
        if own is None or own.peer_pub != peer.device_pub or own.ts >= t_accept:
            continue
        pairs.append((own, peer))
    pairs.sort(key=lambda p: (p[0].ts, p[0].contact_id))
    for x in conflicts:
        x8 = id8(x.tag_hash)
        for own, peer in pairs:
            if x8 in peer.sent_ids or x8 in own.recv_ids:
                return MerchantKnew("PAIRED_CONTACT", x.tag_hash, own.contact_id)
    return None


# R6 LOG_TAMPER (§9.5, server) --------------------------------------------------------


@dataclass(frozen=True)
class LogTamper:
    kind: str  # "FORK" or "BROKEN_LINK"
    seq: int


def log_tamper(entries: Iterable[Dlog]) -> LogTamper | None:
    """R6 for one device's entries: the first fork or broken link by seq.

    A missing seq is not tampering (entries arrive out of order by gossip);
    links are only checked where the previous entry is known.
    """
    by_seq: dict[int, dict[bytes, Dlog]] = {}
    devices = set()
    for e in entries:
        devices.add(e.device_pub)
        by_seq.setdefault(e.seq, {})[e.entry_hash] = e
    if len(devices) > 1:
        raise ValueError("log_tamper checks one device at a time")
    if not devices:
        return None
    device_pub = devices.pop()

    for seq in sorted(by_seq):
        here = by_seq[seq]
        if len(here) > 1:
            return LogTamper("FORK", seq)
        entry = next(iter(here.values()))
        if seq == 1:
            if entry.prev_hash != dlog_genesis(device_pub):
                return LogTamper("BROKEN_LINK", seq)
        elif seq - 1 in by_seq and entry.prev_hash not in by_seq[seq - 1]:
            return LogTamper("BROKEN_LINK", seq)
    return None

