"""Reconcile the double-entry ledger with Capital One Nessie's records (spec §11.4a).

For every real account that has a Nessie account (each resident's checking and
escrow, each real shop, the guarantee pool) this compares, in integer cents:

- what our ledger says Nessie should hold: the opening balance + Σ ledger
  movements on the account, leaving out simulated money (ledger only by design);
- what Nessie's own records add up to: the account's fixed `balance` (its
  opening) + completed deposits − completed withdrawals.

Nessie never changes an account's `balance` and our ledger books no opening
entry, so the opening is compared on its own: ours comes from the logged
"open account" call (or the opening rule: checking $500, escrow and shops $0),
Nessie's from the account itself.

A difference is split transaction by transaction (the `SC <txn_id>` in every
Nessie description is the ledger txn_id), so the explanation items always add
up to the difference exactly. Each pair is also checked: one withdrawal on the
source, one deposit on the destination, both matching the ledger amount.

Read-only: nothing here writes to the ledger or to Nessie.
"""

from __future__ import annotations

import re
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from . import ledger, registry
from .db import all_rows
from .deps import Deps
from .nessie import NessieError, is_whole_dollars, pool_account_id

SC_DESCRIPTION = re.compile(r"^SC ([0-9a-fA-F-]{36})(?:\s|$)")
MAX_ITEMS = 50  # per account; the totals by kind always cover every item
MAX_PAIR_PROBLEMS = 50

KIND_LABELS = {
    "opening": "Opening balance differs",
    "queued": "Queued for Nessie",
    "half_pair": "Half of a pair missing",
    "in_flight": "Changed after Nessie was read",
    "pending_in_nessie": "Not completed in Nessie",
    "ledger_only": "Ledger only",
    "held": "Held, never sent to Nessie",
    "not_in_ledger": "In Nessie, not in our ledger",
    "unlinked": "In Nessie, no SC txn id",
    "unexplained": "Unexplained",
}
SIMULATED_LABEL = "ledger only, never sent to Nessie"


def cents_of(amount) -> int:
    """Nessie amounts are whole dollars (sometimes sent back as 12.0)."""
    return int(Decimal(str(amount)) * 100)


def money(cents: int) -> str:
    sign = "−" if cents < 0 else ""
    return f"{sign}${abs(cents) // 100:,}.{abs(cents) % 100:02d}"


def sc_txn(desc) -> uuid.UUID | None:
    m = SC_DESCRIPTION.match(str(desc or ""))
    if not m:
        return None
    try:
        return uuid.UUID(m.group(1))
    except ValueError:
        return None


def short(txn_id) -> str:
    return str(txn_id)[:8]


def _epoch(ts) -> int:
    return int(ts.timestamp())


# Accounts -----------------------------------------------------------------------


def real_accounts(conn, deps: Deps) -> list[dict]:
    """Every real (not simulated) account that mirrors a Nessie account, in the
    Accounts tab's order. `ledger` lists the ledger accounts it mirrors: a
    resident's escrow covers all of their certificates (one Nessie escrow)."""
    residents = all_rows(conn, "SELECT * FROM residents WHERE NOT simulated ORDER BY created_at")
    certs = defaultdict(list)
    for r in all_rows(conn, """SELECT DISTINCT c.cert_id, c.resident_id FROM certificates c
                               JOIN residents r ON r.resident_id = c.resident_id WHERE NOT r.simulated"""):
        certs[r["resident_id"]].append(bytes(r["cert_id"]))
    merchants = all_rows(conn, "SELECT * FROM merchants WHERE NOT simulated ORDER BY display_name")
    out = []
    for r in residents:
        name = r["display_name"]
        out.append({"key": ledger.checking(r["resident_id"]), "label": f"{name} Checking", "kind": "checking",
                    "nessie_account_id": r["checking_account_id"], "ledger": [ledger.checking(r["resident_id"])]})
        escrows = [ledger.escrow(c) for c in sorted(certs[r["resident_id"]])]
        if escrows:
            out.append({"key": escrows[0], "label": f"{name} Escrow", "kind": "escrow",
                        "nessie_account_id": r["escrow_account_id"], "ledger": escrows})
    for m in merchants:
        key = ledger.merchant(bytes(m["merchant_id"]))
        out.append({"key": key, "label": m["display_name"], "kind": "merchant",
                    "nessie_account_id": m["nessie_account_id"], "ledger": [key]})
    out.append({"key": ledger.POOL, "label": "Guarantee Pool", "kind": "pool",
                "nessie_account_id": pool_account_id(conn, deps.settings), "ledger": [ledger.POOL]})
    return out


def _opening_rule(kind: str) -> int | None:
    """Cents an account is opened at by StormCash's own code (§12.1, demo reset)."""
    return {"checking": registry.CHECKING_OPENING_DOLLARS * 100, "escrow": 0, "merchant": 0}.get(kind)


# The check ----------------------------------------------------------------------


def reconcile(deps: Deps) -> dict:
    checked_at = int(time.time())
    with deps.pool.connection() as conn:
        accounts = real_accounts(conn, deps)
    if deps.nessie is None:
        return {"checked_at": checked_at, "ok": False,
                "nessie": {"enabled": False, "error": None},
                "accounts": [_no_nessie(a, "Nessie is switched off (NESSIE_DISABLED=1): ledger only")
                             for a in accounts],
                "pairs": {"checked": 0, "complete": 0, "problems": [], "problems_total": 0},
                "simulated_town": _town(deps)}

    # Read Nessie first, then the database: anything the ledger gained after the
    # read is then visible as "changed after Nessie was read", not as missing.
    backed = [a for a in accounts if a["nessie_account_id"]]

    def read(account: dict):
        try:
            return deps.nessie.account_records(account["nessie_account_id"]), None
        except (NessieError, KeyError, TypeError) as exc:
            return None, str(exc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        reads = dict(zip((a["key"] for a in backed), pool.map(read, backed), strict=True))

    ok_reads = {k: r for k, (r, err) in reads.items() if r is not None}
    with deps.pool.connection() as conn:
        facts = _Facts.load(conn, accounts, ok_reads, {a["key"]: a for a in backed})

    rows = []
    for a in accounts:
        if not a["nessie_account_id"]:
            rows.append(_no_nessie(a, "No guarantee pool account in Nessie (NESSIE_POOL_ACCOUNT_ID unset): "
                                      "pool money is ledger only" if a["kind"] == "pool" else
                                      "No Nessie account (registered while Nessie was off): ledger only"))
            continue
        snapshot, error = reads[a["key"]]
        if snapshot is None:
            rows.append({**_base(a), "status": "error", "error": error})
            continue
        rows.append(_account(a, snapshot, facts))

    errors = [r["error"] for r in rows if r["status"] == "error"]
    return {
        "checked_at": checked_at,
        "ok": not errors,
        "nessie": {"enabled": True, "error": errors[0] if errors else None},
        "accounts": rows,
        "pairs": _pairs(facts, ok_reads),
        "simulated_town": _town(deps),
    }


def _base(a: dict) -> dict:
    return {"key": a["key"], "label": a["label"], "kind": a["kind"], "nessie_account_id": a["nessie_account_id"]}


def _no_nessie(a: dict, why: str) -> dict:
    return {**_base(a), "status": "no_nessie_account", "error": why}


class _Facts:
    """Everything the check needs from the database, read in a few queries."""

    @classmethod
    def load(cls, conn, accounts: list[dict], reads: dict[str, dict], backed: dict[str, dict]) -> _Facts:
        f = cls()
        f.read_records = {backed[k]["nessie_account_id"]: _records(r) for k, r in reads.items()}
        f.label_of_nessie = {a["nessie_account_id"]: a["label"] for a in accounts if a["nessie_account_id"]}
        f.pool_account_id = next((a["nessie_account_id"] for a in accounts if a["kind"] == "pool"), None)
        f.key_of_ledger = {acct: a["key"] for a in accounts for acct in a["ledger"]}
        ledger_accounts = list(f.key_of_ledger)

        # Every ledger transaction that touches a reconciled account, with all its legs.
        f.entries = defaultdict(list)  # txn_id -> [entry]
        for e in all_rows(conn, """SELECT txn_id, account, debit_cents, credit_cents, ref, created_at
                                   FROM ledger_entries WHERE txn_id IN
                                   (SELECT txn_id FROM ledger_entries WHERE account = ANY(%s))
                                   ORDER BY entry_id""", (ledger_accounts,)):
            f.entries[e["txn_id"]].append(e)

        # The SC txn ids Nessie shows on the accounts we read.
        nessie_txns = {t for r in reads.values() for rec in r["deposits"] + r["withdrawals"]
                       if (t := sc_txn(rec.get("description")))}
        unknown = [t for t in nessie_txns if t not in f.entries]
        f.in_ledger_elsewhere = {r["txn_id"]: r["accounts"] for r in all_rows(
            conn, "SELECT txn_id, array_agg(account) AS accounts FROM ledger_entries WHERE txn_id = ANY(%s) GROUP BY 1",
            (unknown,))}

        ids = [a for a in f.label_of_nessie]
        f.moves = {m["txn_id"]: m for m in all_rows(
            conn, """SELECT * FROM nessie_moves WHERE txn_id = ANY(%s) OR from_account_id = ANY(%s)
                     OR to_account_id = ANY(%s)""",
            (list(f.entries) + list(nessie_txns), ids, ids))}

        # Our own call log: how each account was opened, and the POSTs behind
        # Nessie records whose ledger txn we no longer have.
        patterns = [f"SC {t}%" for t in nessie_txns if t not in f.entries]
        f.opened = {}
        f.posts = defaultdict(list)  # txn_id -> [call]
        for c in all_rows(conn, """SELECT call_id, path, status, request, response, created_at FROM nessie_calls
                                   WHERE method = 'POST' AND (response->'objectCreated'->>'_id' = ANY(%s)
                                         OR request->>'description' LIKE ANY(%s))
                                   ORDER BY call_id""", (ids, patterns)):
            created = (c["response"] or {}).get("objectCreated", {}).get("_id") if isinstance(c["response"], dict) else None
            if created in f.label_of_nessie and c["path"].endswith("/accounts") and c["status"] and c["status"] < 400:
                f.opened[created] = c
            t = sc_txn((c["request"] or {}).get("description"))
            if t:
                f.posts[t].append(c)

        # Who is behind each counterparty: simulated entities are ledger only.
        merchant_hex = {acct.split(":", 1)[1] for legs in f.entries.values() for e in legs
                        if (acct := e["account"]).startswith("merchant:")}
        f.merchants = {bytes(m["merchant_id"]).hex(): m for m in all_rows(
            conn, "SELECT merchant_id, display_name, simulated FROM merchants WHERE merchant_id = ANY(%s)",
            ([bytes.fromhex(h) for h in merchant_hex],))}
        cert_hex = {acct.split(":", 1)[1] for legs in f.entries.values() for e in legs
                    if (acct := e["account"]).startswith("escrow:")}
        f.cert_owner = {bytes(r["cert_id"]).hex(): r for r in all_rows(
            conn, """SELECT DISTINCT c.cert_id, r.display_name, r.simulated FROM certificates c
                     JOIN residents r ON r.resident_id = c.resident_id WHERE c.cert_id = ANY(%s)""",
            ([bytes.fromhex(h) for h in cert_hex],))}
        resident_ids = {acct.split(":", 1)[1] for legs in f.entries.values() for e in legs
                        if (acct := e["account"]).startswith("checking:")}
        f.residents = {str(r["resident_id"]): r for r in all_rows(
            conn, "SELECT resident_id, display_name, simulated FROM residents WHERE resident_id::text = ANY(%s)",
            (list(resident_ids),))}

        # A settlement's ledger txn and its payout row are written in one DB
        # transaction, so they share created_at: that links a txn to its payer.
        settle_merchants = {bytes.fromhex(h) for h in merchant_hex}
        f.payouts = defaultdict(list)  # (merchant hex, cents, source, created_at) -> [payout]
        for p in all_rows(conn, """SELECT po.payout_id, po.merchant_id, po.amount_cents, po.source, po.status,
                                          po.created_at, r.display_name AS payer, r.simulated AS payer_simulated
                                   FROM payouts po
                                   LEFT JOIN payments pm ON pm.tag_hash = po.tag_hash
                                   LEFT JOIN LATERAL (SELECT resident_id FROM certificates c
                                                      WHERE c.cert_id = pm.cert_id LIMIT 1) c ON TRUE
                                   LEFT JOIN residents r ON r.resident_id = c.resident_id
                                   WHERE po.merchant_id = ANY(%s)""", (list(settle_merchants),)):
            f.payouts[(bytes(p["merchant_id"]).hex(), p["amount_cents"], p["source"], p["created_at"])].append(p)
        return f

    # Questions about one transaction ----------------------------------------------

    def amount(self, txn_id) -> int | None:
        legs = self.entries.get(txn_id)
        return sum(e["debit_cents"] for e in legs) if legs else None

    def payout_of(self, txn_id) -> dict | None:
        """The payout row written with a settlement txn (None if not a settlement
        or ambiguous)."""
        legs = self.entries.get(txn_id, [])
        m = next((e for e in legs if e["account"].startswith("merchant:") and e["debit_cents"] > 0
                  and str(e["ref"] or "").startswith("settle from ")), None)
        if m is None:
            return None
        source = str(m["ref"]).removeprefix("settle from ")
        found = self.payouts.get((m["account"].split(":", 1)[1], m["debit_cents"], source, m["created_at"]), [])
        if not found:
            return None
        if len({(p["payer_simulated"], p["status"]) for p in found}) > 1:
            return None
        return found[0]

    def simulated_party(self, txn_id, own: list[str]) -> str | None:
        """The simulated resident or shop behind this txn, if any (by name)."""
        for e in self.entries.get(txn_id, []):
            acct = e["account"]
            if acct in own:
                continue
            kind, _, ident = acct.partition(":")
            if kind == "merchant" and (m := self.merchants.get(ident)) and m["simulated"]:
                return f"simulated shop {m['display_name']}"
            if kind in ("escrow", "fraud_receivable") and (o := self.cert_owner.get(ident)) and o["simulated"]:
                return f"simulated resident {o['display_name']}"
            if kind == "checking" and (r := self.residents.get(ident)) and r["simulated"]:
                return f"simulated resident {r['display_name']}"
        p = self.payout_of(txn_id)
        if p and p["payer_simulated"]:
            return f"simulated resident {p['payer']}"
        return None

    def counterpart(self, txn_id, own: list[str]) -> str:
        names = []
        for e in self.entries.get(txn_id, []):
            if e["account"] in own:
                continue
            kind, _, ident = e["account"].partition(":")
            if kind == "merchant" and ident in self.merchants:
                names.append(self.merchants[ident]["display_name"])
            elif kind == "escrow" and ident in self.cert_owner:
                names.append(f"{self.cert_owner[ident]['display_name']} Escrow")
            elif kind == "checking" and ident in self.residents:
                names.append(f"{self.residents[ident]['display_name']} Checking")
            elif kind == "pool":
                names.append("Guarantee Pool")
            else:
                names.append(e["account"])
        return ", ".join(names) or "?"


def _records(snapshot: dict) -> list[dict]:
    """Deposits (+) and withdrawals (−) as signed cents, with their SC txn id."""
    out = []
    for kind, sign in (("deposits", 1), ("withdrawals", -1)):
        for r in snapshot[kind]:
            out.append({"id": r.get("_id"), "kind": kind[:-1], "cents": sign * cents_of(r.get("amount", 0)),
                        "status": r.get("status"), "description": str(r.get("description") or ""),
                        "date": r.get("transaction_date"), "txn_id": sc_txn(r.get("description"))})
    return out


def _account(a: dict, snapshot: dict, f: _Facts) -> dict:
    own = a["ledger"]
    account_id = a["nessie_account_id"]
    fetched_at = snapshot["fetched_at"]
    records = _records(snapshot)
    completed = [r for r in records if r["status"] == "completed"]

    # Our side: the opening, then every ledger movement by txn.
    nessie_opening = cents_of(snapshot["opening"])
    call = f.opened.get(account_id)
    if call and isinstance((call["request"] or {}).get("balance"), (int, float)):
        opening = {"cents": cents_of(call["request"]["balance"]), "source": "call_log", "call_id": call["call_id"],
                   "at": _epoch(call["created_at"])}
    elif (rule := _opening_rule(a["kind"])) is not None:
        opening = {"cents": rule, "source": "rule", "call_id": None, "at": None}
    else:
        opening = {"cents": nessie_opening, "source": "nessie", "call_id": None, "at": None}
    opening["nessie_cents"] = nessie_opening

    ledger_delta: dict = defaultdict(int)
    for txn_id, legs in f.entries.items():
        d = sum(e["debit_cents"] - e["credit_cents"] for e in legs if e["account"] in own)
        if any(e["account"] in own for e in legs):
            ledger_delta[txn_id] += d
    ledger_cents = sum(ledger_delta.values())

    simulated_cents, simulated_txns, expected_delta = 0, 0, {}
    for txn_id, d in ledger_delta.items():
        if f.simulated_party(txn_id, own) and txn_id not in f.moves:
            simulated_cents += d
            simulated_txns += 1
        else:
            expected_delta[txn_id] = d

    # Nessie's side, by txn.
    nessie_delta: dict = defaultdict(int)
    not_completed = defaultdict(list)
    unlinked = []
    for r in records:
        if r["status"] != "completed":
            if r["txn_id"]:
                not_completed[r["txn_id"]].append(r)
            else:
                unlinked.append(r)
            continue
        if r["txn_id"]:
            nessie_delta[r["txn_id"]] += r["cents"]
        else:
            unlinked.append(r)

    nessie_cents = nessie_opening + sum(r["cents"] for r in completed)
    expected_cents = opening["cents"] + sum(expected_delta.values())
    difference = nessie_cents - expected_cents

    items = []
    if nessie_opening != opening["cents"]:
        where = (f"our call log #{opening['call_id']} opened it at {money(opening['cents'])}"
                 if opening["source"] == "call_log" else f"StormCash opens a {a['kind']} at {money(opening['cents'])}")
        items.append({"kind": "opening", "cents": nessie_opening - opening["cents"], "txn_id": None,
                      "text": f"Nessie's opening balance is {money(nessie_opening)}; {where}."})
    for r in unlinked:
        state = "" if r["status"] == "completed" else f" (status {r['status']}, not counted)"
        cents = r["cents"] if r["status"] == "completed" else 0
        if cents:
            items.append({"kind": "unlinked", "cents": cents, "txn_id": None,
                          "text": f"Nessie {r['kind']} {money(abs(r['cents']))} on {r['date']} "
                                  f"\"{r['description'][:60]}\" has no SC txn id{state}."})
    for txn_id in sorted(set(expected_delta) | set(nessie_delta) | set(not_completed), key=str):
        d = nessie_delta.get(txn_id, 0) - expected_delta.get(txn_id, 0)
        if d:
            kind, text = _explain(txn_id, a, f, own, expected_delta.get(txn_id, 0), nessie_delta.get(txn_id, 0),
                                  not_completed.get(txn_id), fetched_at)
            items.append({"kind": kind, "cents": d, "txn_id": str(txn_id), "text": text})
    rest = difference - sum(i["cents"] for i in items)
    if rest:  # can't happen by construction; never hide it if it does
        items.append({"kind": "unexplained", "cents": rest, "txn_id": None,
                      "text": f"{money(rest)} not accounted for by any transaction."})

    by_kind: dict = {}
    for i in items:
        k = by_kind.setdefault(i["kind"], {"kind": i["kind"], "label": KIND_LABELS[i["kind"]], "count": 0, "cents": 0})
        k["count"] += 1
        k["cents"] += i["cents"]

    return {
        **_base(a),
        "status": "reconciled" if difference == 0 else "difference",
        "error": None,
        "fetched_at": fetched_at,
        "opening": opening,
        "ledger_cents": ledger_cents,
        "simulated": {"cents": simulated_cents, "txns": simulated_txns, "label": SIMULATED_LABEL}
        if simulated_txns else None,
        "expected_cents": expected_cents,
        "nessie_cents": nessie_cents,
        "difference_cents": difference,
        "records": {"deposits": len(snapshot["deposits"]), "withdrawals": len(snapshot["withdrawals"]),
                    "linked": sum(1 for r in records if r["txn_id"]), "unlinked": len(unlinked),
                    "not_completed": sum(1 for r in records if r["status"] != "completed")},
        "by_kind": list(by_kind.values()),
        "items": items[:MAX_ITEMS],
        "items_total": len(items),
    }


def _explain(txn_id, a: dict, f: _Facts, own: list[str], ledger_d: int, nessie_d: int,
             pending: list[dict] | None, fetched_at: int) -> tuple[str, str]:
    """Why this txn's Nessie records and ledger entries differ on this account."""
    tag = f"SC {short(txn_id)}…"
    move = f.moves.get(txn_id)
    in_ledger = txn_id in f.entries

    if pending:
        r = pending[0]
        return "pending_in_nessie", (f"{tag}: Nessie {r['kind']} {money(abs(r['cents']))} has status "
                                     f"'{r['status']}', so it doesn't count yet.")

    if not in_ledger:
        nessie_side = f"Nessie {'deposit' if nessie_d > 0 else 'withdrawal'} {money(abs(nessie_d))}"
        rec_desc = _record_desc(f, txn_id)
        elsewhere = f.in_ledger_elsewhere.get(txn_id)
        if elsewhere:
            return "unexplained", (f"{tag}: {nessie_side} here, but ledger txn {short(txn_id)}… is on "
                                   f"{', '.join(elsewhere)}, not on {a['label']}.")
        posts = f.posts.get(txn_id, [])
        if posts:
            when = time.strftime("%b %d %H:%M", time.localtime(_epoch(posts[0]["created_at"])))
            other = [c for c in posts if a["nessie_account_id"] not in c["path"]]
            other_txt = (f"; its other half went to {_account_name(f, other[0]['path'])}" if other else "")
            source = f"our call log has the POST from {when} (#{posts[0]['call_id']}){other_txt}"
        else:
            source = "not in our call log either"
        return "not_in_ledger", (f"{tag} {rec_desc}: {nessie_side}, no ledger transaction with this id; {source}.")

    if move is not None:
        w_here, d_here = _halves(f, txn_id, move)
        label = f"{move['summary']} {money(move['amount_cents'])}"
        if move["status"] == "queued":
            if not w_here and not d_here:
                since = time.strftime("%H:%M:%S", time.localtime(_epoch(move["created_at"])))
                return "queued", (f"{tag} {label}: queued since {since}, {move['attempts']} attempt(s); "
                                  f"the server retries every 10 s and creates only the missing half.")
            have, missing = ("withdrawal", "deposit") if w_here else ("deposit", "withdrawal")
            return "half_pair", (f"{tag} {label}: the {have} is in Nessie, the {missing} isn't yet "
                                 f"(queued, {move['attempts']} attempt(s)).")
        if _epoch(move["updated_at"]) >= fetched_at and nessie_d == 0:
            return "in_flight", (f"{tag} {label}: sent to Nessie after this account was read at "
                                 f"{time.strftime('%H:%M:%S', time.localtime(fetched_at))}; re-check.")
        if nessie_d == 0:
            return "unexplained", (f"{tag} {label}: our queue says both halves exist (deposit "
                                   f"{move['deposit_id']}), but Nessie lists no record on {a['label']}.")
        return "unexplained", (f"{tag} {label}: Nessie records {money(nessie_d)} on {a['label']}, "
                               f"the ledger {money(ledger_d)}.")

    if nessie_d:
        return "unexplained", (f"{tag}: Nessie records {money(nessie_d)} on {a['label']}, the ledger "
                               f"{money(ledger_d)}, and no Nessie move was queued for it.")
    created = min(_epoch(e["created_at"]) for e in f.entries[txn_id])
    when = time.strftime("%H:%M:%S", time.localtime(created))
    ref = f.entries[txn_id][0]["ref"] or "ledger txn"
    with_whom = f.counterpart(txn_id, own)
    amount = f.amount(txn_id) or 0
    payout = f.payout_of(txn_id)
    if not is_whole_dollars(amount):
        return "ledger_only", (f"{tag} {ref} {money(amount)} with {with_whom} at {when}: not whole dollars, "
                               f"ledger only (Nessie takes whole dollars).")
    if (payout and payout["status"] == "held") or ref == "pool payout held":
        return "held", (f"{tag} {ref} {money(amount)} with {with_whom} at {when}: a pool payout held by an "
                        f"approved hold_pool_payout is booked and reversed in the ledger, never sent to Nessie.")
    if payout and payout["source"] == "pool" and not f.pool_account_id:
        return "ledger_only", (f"{tag} {ref} {money(amount)} with {with_whom} at {when}: "
                               f"no guarantee pool account in Nessie, ledger only.")
    if payout and payout["status"] == "ledger_only":
        return "ledger_only", (f"{tag} {ref} {money(amount)} with {with_whom} at {when}: payout "
                               f"#{payout['payout_id']} is ledger_only.")
    return "unexplained", (f"{tag} {ref} {money(amount)} with {with_whom} at {when}: whole dollars between "
                           f"real accounts, but no Nessie move was queued.")


def _record_desc(f: _Facts, txn_id) -> str:
    """The summary after "SC <txn_id>" in the Nessie description, quoted."""
    descs = [r["description"] for recs in f.read_records.values() for r in recs if r["txn_id"] == txn_id]
    descs += [str((c["request"] or {}).get("description", "")) for c in f.posts.get(txn_id, [])]
    for desc in descs:
        rest = desc.split(" ", 2)[2] if desc.count(" ") >= 2 else ""
        if rest:
            return f"\"{rest}\""
    return ""


def _halves(f: _Facts, txn_id, move: dict) -> tuple[bool, bool]:
    """Whether the move's withdrawal and deposit are recorded in Nessie (from the
    read accounts' records, else from the ids the queue stored)."""
    w = any(r["txn_id"] == txn_id for r in f.read_records.get(move["from_account_id"], [])
            if r["kind"] == "withdrawal") if move["from_account_id"] in f.read_records else bool(move["withdrawal_id"])
    d = any(r["txn_id"] == txn_id for r in f.read_records.get(move["to_account_id"], [])
            if r["kind"] == "deposit") if move["to_account_id"] in f.read_records else bool(move["deposit_id"])
    return w, d


def _account_name(f: _Facts, path: str) -> str:
    parts = path.strip("/").split("/")
    account_id = parts[1] if len(parts) > 1 and parts[0] == "accounts" else path
    return f.label_of_nessie.get(account_id, f"Nessie account …{account_id[-6:]} (no longer a StormCash account)")


# Pairs --------------------------------------------------------------------------


def _pairs(f: _Facts, reads: dict[str, dict]) -> dict:
    """Each `SC <txn_id>` pair: one completed withdrawal and one completed deposit,
    equal, matching the ledger amount, on the accounts the queue named."""
    read_ids = set(f.read_records)
    txns = {r["txn_id"] for recs in f.read_records.values() for r in recs if r["txn_id"]}
    txns |= {t for t, m in f.moves.items() if m["from_account_id"] in read_ids or m["to_account_id"] in read_ids}
    by_txn = defaultdict(list)
    for account_id, recs in f.read_records.items():
        for r in recs:
            if r["txn_id"]:
                by_txn[r["txn_id"]].append({**r, "account_id": account_id})

    complete, problems = 0, []
    for txn_id in sorted(txns, key=str):
        recs = [r for r in by_txn.get(txn_id, []) if r["status"] == "completed"]
        ws = [r for r in recs if r["kind"] == "withdrawal"]
        ds = [r for r in recs if r["kind"] == "deposit"]
        move = f.moves.get(txn_id)
        ledger_amount = f.amount(txn_id)
        tag = f"SC {short(txn_id)}…"
        problem = None
        if move is not None:
            name = f"{move['summary']} {money(move['amount_cents'])}"
            from_read, to_read = move["from_account_id"] in read_ids, move["to_account_id"] in read_ids
            w_ok = [r for r in ws if r["account_id"] == move["from_account_id"]] if from_read else None
            d_ok = [r for r in ds if r["account_id"] == move["to_account_id"]] if to_read else None
            if ledger_amount is None:
                problem = ("not_in_ledger", f"{tag} {name}: queued move with no ledger transaction.")
            elif move["amount_cents"] != ledger_amount:
                problem = ("amount_mismatch", f"{tag} {name}: queued {money(move['amount_cents'])}, "
                                              f"ledger {money(ledger_amount)}.")
            elif (w_ok is not None and len(w_ok) > 1) or (d_ok is not None and len(d_ok) > 1):
                problem = ("duplicate", f"{tag} {name}: {len(w_ok or [])} withdrawals, {len(d_ok or [])} deposits.")
            elif w_ok == [] and d_ok == []:
                problem = ("queued", f"{tag} {name}: neither half in Nessie yet ({move['status']}, "
                                     f"{move['attempts']} attempt(s)).")
            elif w_ok == [] or d_ok == []:
                missing = "withdrawal" if w_ok == [] else "deposit"
                problem = ("half_pair", f"{tag} {name}: the {missing} on "
                                        f"{_label(f, move['from_account_id' if missing == 'withdrawal' else 'to_account_id'])}"
                                        f" is missing ({move['status']}).")
            elif any(abs(r["cents"]) != ledger_amount for r in (w_ok or []) + (d_ok or [])):
                problem = ("amount_mismatch", f"{tag} {name}: Nessie amounts "
                           f"{', '.join(money(abs(r['cents'])) for r in (w_ok or []) + (d_ok or []))}, "
                           f"ledger {money(ledger_amount)}.")
            elif not from_read or not to_read:
                side = "withdrawal" if not from_read else "deposit"
                acct = move["from_account_id"] if not from_read else move["to_account_id"]
                stored = move["withdrawal_id"] if side == "withdrawal" else move["deposit_id"]
                problem = ("unverified", f"{tag} {name}: the {side} is on {_label(f, acct)}, which isn't read; "
                                         f"the queue stored its id ({stored})." if stored else
                                         f"{tag} {name}: the {side} is on {_label(f, acct)}, which isn't read, "
                                         f"and the queue has no id for it.")
        else:
            if ledger_amount is None:
                problem = ("not_in_ledger", f"{tag} {_record_desc(f, txn_id)}: in Nessie "
                                            f"({_n(len(ws), 'withdrawal')}, {_n(len(ds), 'deposit')} on the "
                                            f"accounts read), no ledger transaction and no queued move.")
            else:
                problem = ("no_move", f"{tag}: in Nessie and in the ledger, but never queued as a move.")
        if problem is None:
            complete += 1
        else:
            problems.append({"txn_id": str(txn_id), "kind": problem[0], "text": problem[1]})
    return {"checked": len(txns), "complete": complete, "problems": problems[:MAX_PAIR_PROBLEMS],
            "problems_total": len(problems)}


def _n(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _label(f: _Facts, account_id: str) -> str:
    return f.label_of_nessie.get(account_id, f"Nessie account …{account_id[-6:]}")


def _town(deps: Deps) -> dict:
    """Simulated shops' ledger money: never sent to Nessie, so never a difference."""
    with deps.pool.connection() as conn:
        row = all_rows(conn, """SELECT count(DISTINCT m.merchant_id) AS merchants,
                                       COALESCE(SUM(e.debit_cents - e.credit_cents), 0) AS cents
                                FROM merchants m LEFT JOIN ledger_entries e
                                  ON e.account = 'merchant:' || encode(m.merchant_id, 'hex')
                                WHERE m.simulated""")[0]
    return {"label": f"Simulated town: {SIMULATED_LABEL}", "merchants": row["merchants"],
            "merchant_cents": int(row["cents"])}
