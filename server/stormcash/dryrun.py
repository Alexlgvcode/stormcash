"""Demo dry run (spec §21.6): the server side of the 2:30 judge demo, headless.

    python -m stormcash.dryrun --base-url http://localhost:8000

Three labelled test identities, "Dry-run Maya", "Dry-run Pharmacy" and "Dry-run
Gas Station", each with a fresh key of its own, play the phones' part with the
real protocol library: register, Storm Mode, a $12 payment the pharmacy checks
C1–C6 offline, both judge-mode rollbacks refused by C6 at the gas station, and
the gas station's upload carrying the pharmacy's payment two hops. Every beat
prints ✓ or ✗ with a one-line reason. Then it checks the proof, the seeded
town's Corner Store flag, and cleans up with POST /v1/demo/reset (which removes
every dry-run identity first), so the table is ready for the next judge.

It never signs as the real Maya (her key is on her phone), never writes to the
simulated town, and never starts StormDesk: the server's worker skips dry-run
identities, and the dry run refuses a server that can't say so. It reads
server/.env for DATABASE_URL (checks only; it writes through the API) and the
Nessie key (it reads Nessie directly to see what the bank recorded).

Exit code 0 only when every step passed. --keep skips the cleanup.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values

from . import ledger
from .auth import sign_request
from .config import SERVER_DIR
from .db import all_rows, make_pool, one, scalar
from .demo import DRY_RUN_PREFIX
from .protocol import crypto, rules
from .protocol.objects import (Cert, Det, Dlog, Item, Mcert, Pay, Policy, Proof, Rcpt, Req, Tag, b64u_decode,
                               b64u_encode, contact_id, device_short_id, dlog_genesis, genesis, id8)

REPO_DIR = SERVER_DIR.parent
VERIFY_BIN = REPO_DIR / "cpp" / "build" / "verify" / "stormcash-verify"
MOBILE_CONFIG = REPO_DIR / "mobile" / "src" / "config.ts"
OPERATOR = {"X-SC-Operator": "dry-run"}
BASE_CAP_CENTS = 2000
STORM_CAP_CENTS = 5000
PRICE_CENTS = 1200  # the demo's $12 (whole dollars: real entities settle in Nessie)
CHECKING_OPENING_CENTS = 50000


class Failed(Exception):
    """A beat that didn't go the way the demo needs. The message is the one-line reason."""


def need(ok: Any, reason: str) -> None:
    if not ok:
        raise Failed(reason)


def plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def dollars(cents: int) -> str:
    return f"${cents // 100}" if cents % 100 == 0 else f"${cents / 100:.2f}"


def parse_pub(text: str) -> bytes:
    """A SEC1 compressed key as hex or base64url."""
    text = text.strip()
    pub = bytes.fromhex(text) if re.fullmatch(r"[0-9a-fA-F]{66}", text) else b64u_decode(text)
    crypto.load_public_key(pub)
    return pub


def mobile_server_pub(path: Path = MOBILE_CONFIG) -> bytes | None:
    """SERVER_PUB as compiled into the phone app (mobile/src/config.ts), if this checkout has it."""
    try:
        m = re.search(r"SERVER_PUB\s*=\s*'([0-9a-f]{66})'", path.read_text())
    except OSError:
        return None
    return bytes.fromhex(m.group(1)) if m else None


# The phones ------------------------------------------------------------------------------------


@dataclass
class Phone:
    """One test identity and what its phone holds: items (with their gossip path) and its device log."""

    name: str
    key: Any = field(default_factory=crypto.generate_private_key)
    items: dict[bytes, Item] = field(default_factory=dict)
    log: list[Dlog] = field(default_factory=list)

    @property
    def pub(self) -> bytes:
        return crypto.public_key_bytes(self.key)

    @property
    def short(self) -> str:
        return device_short_id(self.pub)

    def keep(self, item: Item) -> None:
        self.items[item.id] = item  # a PAY replaces the TAG with the same id (§10.2)

    def append(self, ts: int, kind: str, **body) -> Dlog:
        """Sign the next DLOG entry (§9.2) and carry it like any other item."""
        prev = self.log[-1].entry_hash if self.log else dlog_genesis(self.pub)
        entry = Dlog(device_pub=self.pub, seq=len(self.log) + 1, prev_hash=prev, ts=ts, kind=kind, **body)
        entry = entry.signed(self.key)
        self.log.append(entry)
        self.keep(Item("DLOG", entry, ((self.short, ts),)))
        return entry

    def tags_for(self, cert_id: bytes, holder_pub: bytes) -> list[Tag]:
        """Every tag this phone holds for a cert, signed by its holder (what C6 checks against)."""
        tags: dict[bytes, Tag] = {}
        for item in self.items.values():
            found = [item.body.tag] if item.kind == "PAY" else [item.body] if item.kind == "TAG" else \
                [item.body.a, item.body.b] if item.kind == "PROOF" else []
            for t in found:
                if t.cert_id == cert_id and t.verify(holder_pub):
                    tags[t.tag_hash] = t
        return list(tags.values())


def meet(a: Phone, b: Phone, ts: int) -> None:
    """One sync session (§10.3): each side takes the items it lacks (a PAY supersedes a TAG), adds its hop
    to their path, and logs a CONTACT entry naming the TAG/PAY/PROOF ids that moved (§9.2)."""
    na, nb = crypto.random_nonce(), crypto.random_nonce()
    moved: dict[str, list[bytes]] = {a.name: [], b.name: []}
    for src, dst in ((a, b), (b, a)):
        for item_id, item in list(src.items.items()):
            have = dst.items.get(item_id)
            if have is None or (have.kind == "TAG" and item.kind == "PAY"):
                dst.keep(Item(item.kind, item.body, item.path + ((dst.short, ts),)))
                if item.kind in ("TAG", "PAY", "PROOF"):
                    moved[src.name].append(id8(item_id))
    cid = contact_id(a.pub, na, b.pub, nb)
    for me, peer in ((a, b), (b, a)):
        me.append(ts, "CONTACT", contact_id=cid, peer_pub=peer.pub, sent_ids=tuple(moved[me.name]),
                  recv_ids=tuple(moved[peer.name]), sent_overflow=0, recv_overflow=0)


@dataclass
class Wallet:
    """Maya's wallet, with judge mode's rollback exactly as mobile/src/store/wallet.ts does it (§19.3)."""

    cert: Cert
    counter: int = 0
    cum: int = 0
    head: bytes = b""
    history: dict[int, tuple[int, bytes]] = field(default_factory=dict)  # counter -> (cum, head) before it

    def __post_init__(self) -> None:
        self.head = genesis(self.cert.cert_id)

    def pay(self, key, mcert: Mcert, req: Req, ts: int) -> Pay:
        det = Det(mcert.merchant_pub, req.nonce, ts)
        tag = Tag(self.cert.cert_id, self.counter + 1, self.head, req.amount_cents, self.cum + req.amount_cents,
                  det.digest()).signed(key)
        self.history[tag.counter] = (self.cum, self.head)
        self.counter, self.cum, self.head = tag.counter, tag.cum_cents, tag.tag_hash
        return Pay(self.cert, tag, det)

    def roll_back(self, mode: str) -> None:
        """"reuse": back to before the last payment. "clever": the same, then the next counter skips one."""
        last = max(k for k in self.history if k <= self.counter)
        self.cum, self.head = self.history[last]
        self.counter = last - 1 if mode == "reuse" else last


def qr(obj: dict) -> str:
    return "SC1:" + json.dumps(obj, separators=(",", ":"))


def from_qr(text: str) -> dict:
    need(text.startswith("SC1:"), "QR payload without the SC1: prefix")
    return json.loads(text[4:])


def payer_check(qr_text: str, server_pub: bytes, cert: Cert, cum: int, now: int) -> tuple[Mcert, Req]:
    """§8.1 on the resident's phone, before signing."""
    data = from_qr(qr_text)
    mcert, req = Mcert.from_json(data["mc"]), Req.from_json(data["rq"])
    need(mcert.verify(server_pub) and mcert.expires_at > now, f"Maya's phone rejects {mcert.display_name}'s MCERT")
    need(req.verify(mcert.merchant_pub) and req.req_expires_at > now - rules.CLOCK_TOLERANCE_S,
         f"Maya's phone rejects {mcert.display_name}'s request signature")
    need(req.amount_cents <= cert.cap_cents - cum, "Maya's phone says: Over your limit")
    return mcert, req


def receive(shop: Phone, mcert: Mcert, req: Req, pay_qr: str, policy: Policy | None, server_pub: bytes,
            now: int) -> tuple[Pay, rules.CheckResult]:
    """A merchant scans a PAY (§8.2): C1–C6, then store it and log ACCEPT, or keep evidence and log REFUSE,
    as mobile/src/payments.ts receivePayment does."""
    pay = Pay.from_json(from_qr(pay_qr))
    held = shop.tags_for(pay.tag.cert_id, pay.cert.holder_pub)
    result = rules.merchant_check(pay, server_pub=server_pub, merchant=mcert, req=req, policy=policy,
                                  stored_tags=held, now=now)
    hop = ((shop.short, now),)
    th = pay.tag.tag_hash
    if result.ok:
        shop.keep(Item("PAY", pay, hop))
        shop.append(now, "ACCEPT", tag_hash=th, cert_id=pay.tag.cert_id,
                    held_ids=tuple(t.tag_hash for t in held if t.tag_hash != th))
    else:
        if result.check == "C6":
            shop.keep(Item("PAY", pay, hop))  # evidence
            proof = rules.make_proof(result.conflict, pay.tag) if result.conflict else None
            if proof:
                shop.keep(Item("PROOF", proof, hop))
        shop.append(now, "REFUSE", tag_hash=th, cert_id=pay.tag.cert_id, check=result.check)
    return pay, result


# Schema --------------------------------------------------------------------------------------


def schema_tables(text: str) -> dict[str, dict]:
    """Tables, columns and CHECK (col IN (...)) values declared in schema.sql."""
    text = re.sub(r"--[^\n]*", "", text)
    out: dict[str, dict] = {}
    for m in re.finditer(r"CREATE TABLE (?:IF NOT EXISTS )?(\w+)\s*\(", text, re.I):
        i, depth = m.end(), 1
        while depth:
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        parts, depth, cur = [], 0, ""
        for c in text[m.end():i - 1]:
            if c == "," and depth == 0:
                parts.append(cur)
                cur = ""
                continue
            depth += {"(": 1, ")": -1}.get(c, 0)
            cur += c
        parts.append(cur)
        columns, checks = [], {}
        for part in (p.strip() for p in parts):
            if not part or part.split()[0].upper() in ("PRIMARY", "UNIQUE", "CHECK", "FOREIGN", "CONSTRAINT"):
                continue
            columns.append(part.split()[0])
            for c in re.finditer(r"CHECK\s*\(\s*(\w+)\s+IN\s*\(([^)]*)\)", part, re.I | re.S):
                checks[c.group(1)] = re.findall(r"'([^']*)'", c.group(2))
        out[m.group(1)] = {"columns": columns, "checks": checks}
    return out


def schema_problems(conn, schema_sql: str) -> list[str]:
    """What the database lacks compared with schema.sql (a migration not applied yet)."""
    have: dict[str, set[str]] = {}
    for r in all_rows(conn, "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public'"):
        have.setdefault(r["table_name"], set()).add(r["column_name"])
    checks: dict[str, list[str]] = {}
    for r in all_rows(conn, """SELECT conrelid::regclass::text AS t, pg_get_constraintdef(oid) AS d FROM pg_constraint
                               WHERE contype = 'c' AND connamespace = 'public'::regnamespace"""):
        checks.setdefault(r["t"].removeprefix("public."), []).append(r["d"])
    problems = []
    for table, spec in schema_tables(schema_sql).items():
        if table not in have:
            problems.append(f"table {table}")
            continue
        problems += [f"{table}.{c}" for c in spec["columns"] if c not in have[table]]
        for col, values in spec["checks"].items():
            defs = [d for d in checks.get(table, []) if re.search(rf"\b{col}\b", d)]
            lacking = [v for v in values if not any(f"'{v}'" in d for d in defs)]
            if lacking:
                problems.append(f"{table}.{col} CHECK without {', '.join(lacking)}")
    return problems


# Nessie --------------------------------------------------------------------------------------


class NessieReader:
    """Reads Nessie directly, not through the server, to see what the bank recorded (§11.4)."""

    def __init__(self, base_url: str, key: str, transport: httpx.BaseTransport | None = None) -> None:
        self._key = key
        self._http = httpx.Client(base_url=base_url, timeout=10, transport=transport)

    def get(self, path: str) -> Any:
        resp = self._http.get(path, params={"key": self._key})
        if resp.status_code >= 400:
            raise Failed(f"Nessie GET {path.split('?')[0]}: HTTP {resp.status_code}")
        return resp.json()

    def records(self, account_id: str, kind: str) -> list[dict]:
        return self.get(f"/accounts/{account_id}/{kind}")

    def balances(self, account_ids: list[str]) -> list[int]:
        """Opening balance + deposits − withdrawals, in cents, for each account (the server's formula)."""
        paths = [f"/accounts/{a}{suffix}" for a in account_ids for suffix in ("", "/deposits", "/withdrawals")]
        with ThreadPoolExecutor(max_workers=12) as pool:
            got = list(pool.map(self.get, paths))
        out = []
        for i in range(0, len(got), 3):
            account, deposits, withdrawals = got[i:i + 3]
            out.append(round((account["balance"] + sum(d["amount"] for d in deposits)
                              - sum(w["amount"] for w in withdrawals)) * 100))
        return out

    def close(self) -> None:
        self._http.close()


# The dry run ---------------------------------------------------------------------------------


@dataclass
class Step:
    title: str
    run: Callable[[], str]
    needs: tuple[int, ...]


class DryRun:
    def __init__(self, http: httpx.Client, pool, *, server_pub: bytes, server_pub_source: str,
                 nessie: NessieReader | None, verify_bin: Path | None = VERIFY_BIN, keep: bool = False,
                 mobile_pub: bytes | None = None, out=None) -> None:
        self.http = http
        self.pool = pool
        self.server_pub = server_pub
        self.server_pub_source = server_pub_source
        self.nessie = nessie
        self.verify_bin = verify_bin
        self.keep = keep
        self.mobile_pub = mobile_pub
        self.out = out or sys.stdout
        self.maya = Phone(f"{DRY_RUN_PREFIX}Maya")
        self.pharmacy = Phone(f"{DRY_RUN_PREFIX}Pharmacy")
        self.gas = Phone(f"{DRY_RUN_PREFIX}Gas Station")
        self.mcerts: dict[str, Mcert] = {}
        self.nessie_on = False
        self.results: list[tuple[int, str, bool | None, str, float]] = []

    # HTTP

    def get(self, path: str, **params) -> Any:
        resp = self.http.get(path, params=params or None)
        if resp.status_code >= 400:
            raise Failed(f"GET {path}: HTTP {resp.status_code} {resp.text[:160]}")
        return resp.json()

    def post(self, path: str, payload: dict, phone: Phone | None = None) -> Any:
        body = json.dumps(payload).encode()
        headers = {"content-type": "application/json"}
        headers.update(sign_request(phone.key, path, body) if phone else OPERATOR)
        resp = self.http.post(path, content=body, headers=headers)
        if resp.status_code >= 400:
            raise Failed(f"POST {path}: HTTP {resp.status_code} {resp.text[:160]}")
        return resp.json()

    def latest_policy(self) -> Policy:
        policy = Policy.from_json(self.get("/v1/policy")["policy"])
        need(policy.verify(self.server_pub), f"POLICY v{policy.policy_ver} isn't signed by SERVER_PUB")
        return policy

    def money(self, *accounts: tuple[str | None, str]) -> list[int]:
        """Balances of (Nessie account id, ledger account) pairs: from Nessie transactions when the server
        uses Nessie, else from the ledger (NESSIE_DISABLED=1)."""
        if self.nessie_on:
            need(all(a for a, _ in accounts), "a dry-run entity has no Nessie account")
            return self.nessie.balances([a for a, _ in accounts])
        with self.pool.connection() as conn:
            return [ledger.balance(conn, name) for _, name in accounts]

    @property
    def source(self) -> str:
        return "in Nessie" if self.nessie_on else "in the ledger (NESSIE_DISABLED=1)"

    # 1 -----------------------------------------------------------------------------------------

    def preflight(self) -> str:
        try:
            health = self.get("/v1/health")
        except httpx.HTTPError as exc:
            raise Failed(f"no server at {self.http.base_url} ({type(exc).__name__})") from exc
        need(health.get("ok"), "GET /v1/health isn't ok")
        signing = b64u_decode(health["server_pub"])
        need(signing == self.server_pub, f"the server signs with {signing.hex()[:12]}…, but SERVER_PUB "
                                         f"({self.server_pub_source}) is {self.server_pub.hex()[:12]}…")
        resp = self.http.get("/v1/demo/dry-run")
        need(resp.status_code == 200, "refusing to run: this server can't say its StormDesk worker skips dry-run "
                                      "data (no GET /v1/demo/dry-run), so the dry run's case could start Droid. "
                                      "Restart it from current main")
        info = resp.json()
        need(info.get("stormdesk_skips_dry_run") is True and info.get("prefix") == DRY_RUN_PREFIX,
             f"refusing to run: StormDesk doesn't skip {DRY_RUN_PREFIX!r} identities on this server")
        self.nessie_on = bool(health.get("nessie_enabled"))
        need(not self.nessie_on or self.nessie is not None,
             "the server uses Nessie but NESSIE_API_KEY isn't in server/.env here, so Nessie can't be checked")

        policy = Policy.from_json(self.get("/v1/policy")["policy"])
        with self.pool.connection() as conn:
            row = one(conn, "SELECT policy_ver, server_sig FROM policy_versions ORDER BY policy_ver DESC LIMIT 1")
            need(row and row["policy_ver"] == policy.policy_ver and bytes(row["server_sig"]) == policy.sig,
                 "the server uses another database than DATABASE_URL in server/.env (latest POLICY differs)")
            problems = schema_problems(conn, (SERVER_DIR / "schema.sql").read_text())
            need(not problems, f"database behind schema.sql, apply server/migrations: missing {', '.join(problems[:6])}")
            runs = one(conn, "SELECT count(*) AS n, COALESCE(MAX(run_id), 0) AS top FROM stormdesk_runs")
            leftovers = scalar(conn, """SELECT (SELECT count(*) FROM residents WHERE starts_with(display_name, %s))
                                            + (SELECT count(*) FROM merchants WHERE starts_with(display_name, %s))""",
                               (DRY_RUN_PREFIX, DRY_RUN_PREFIX))
        self.runs_before = (runs["n"], runs["top"])
        worker = "worker on" if info["stormdesk_worker"] else "worker off"
        notes = [f"{plural(leftovers, 'leftover')} of an earlier --keep run go at cleanup"] if leftovers else []
        if self.mobile_pub is not None and self.mobile_pub != self.server_pub:
            notes.append(f"mobile/src/config.ts still has {self.mobile_pub.hex()[:12]}…, so phones need the demo-menu "
                         "override")
        return (f"server key {signing.hex()[:12]}… = SERVER_PUB ({self.server_pub_source}); database matches "
                f"schema.sql; StormDesk skips dry-run data ({worker}, runner {info['stormdesk_runner']}); "
                f"{plural(runs['n'], 'StormDesk run')} so far" + "".join(f". Note: {n}" for n in notes))

    # 2 -----------------------------------------------------------------------------------------

    def register(self) -> str:
        out = self.post("/v1/residents/register",
                        {"display_name": self.maya.name, "holder_pub": b64u_encode(self.maya.pub)}, self.maya)
        self.resident_id = out["resident_id"]
        cert = Cert.from_json(out["cert"])
        need(cert.verify(self.server_pub), "Maya's CERT isn't signed by SERVER_PUB (C1 would fail)")
        need((cert.holder_pub, cert.cert_ver, cert.cap_cents) == (self.maya.pub, 1, BASE_CAP_CENTS),
             f"unexpected CERT v{cert.cert_ver}, cap {cert.cap_cents}")
        self.wallet = Wallet(cert)
        for phone in (self.pharmacy, self.gas):
            out = self.post("/v1/merchants/register",
                            {"display_name": phone.name, "merchant_pub": b64u_encode(phone.pub)}, phone)
            mcert = Mcert.from_json(out["mcert"])
            need(mcert.verify(self.server_pub) and mcert.merchant_pub == phone.pub,
                 f"{phone.name}'s MCERT isn't signed by SERVER_PUB")
            self.mcerts[phone.name] = mcert
        with self.pool.connection() as conn:
            self.resident = one(conn, "SELECT * FROM residents WHERE resident_id = %s", (self.resident_id,))
            need(self.resident, "registered, but the resident isn't in the database from server/.env")
            self.shops = {m["display_name"]: m for m in all_rows(
                conn, "SELECT * FROM merchants WHERE merchant_id = ANY(%s)",
                ([m.merchant_id for m in self.mcerts.values()],))}
            need(scalar(conn, "SELECT count(*) FROM certificates WHERE cert_id = %s", (cert.cert_id,)) == 1,
                 "the CERT isn't stored")
        r = self.resident
        shop_accounts = [(self.shops[p.name]["nessie_account_id"], ledger.merchant(self.mcerts[p.name].merchant_id))
                         for p in (self.pharmacy, self.gas)]
        checking, escrow, *shops = self.money((r["checking_account_id"], ledger.checking(r["resident_id"])),
                                              (r["escrow_account_id"], ledger.escrow(cert.cert_id)), *shop_accounts)
        need(escrow == BASE_CAP_CENTS, f"escrow holds {dollars(escrow)} {self.source}, not $20 after the lock")
        need(shops == [0, 0], f"the shops hold {[dollars(s) for s in shops]}, not $0")
        self.escrow_cents = escrow
        if not self.nessie_on:  # the ledger's checking account is a mirror, not a balance to show
            return f"{self.maya.name} CERT v1 ($20) and two MCERTs, all under SERVER_PUB; {self.source}: escrow $20"
        need(checking == CHECKING_OPENING_CENTS - BASE_CAP_CENTS, f"checking holds {dollars(checking)}, not $480")
        need(cert.escrow_ref == r["escrow_account_id"], "the CERT's escrow_ref isn't the Nessie escrow account")
        return (f"{self.maya.name} CERT v1 ($20) and two MCERTs, all under SERVER_PUB; accounts in Nessie: "
                f"checking {dollars(checking)}, escrow {dollars(escrow)}, shops $0")

    # 3 -----------------------------------------------------------------------------------------

    def storm_mode(self) -> str:
        before = self.wallet.cert
        cert = Cert.from_json(self.post("/v1/storm-mode", {"cert_id": b64u_encode(before.cert_id),
                                                           "cap_cents": STORM_CAP_CENTS}, self.maya)["cert"])
        need(cert.verify(self.server_pub), "the Storm Mode CERT isn't signed by SERVER_PUB")
        need(cert.cert_id == before.cert_id and cert.cert_ver > before.cert_ver and cert.cap_cents == STORM_CAP_CENTS,
             f"Storm Mode gave CERT v{cert.cert_ver} at cap {dollars(cert.cap_cents)}")
        self.wallet.cert = cert
        (escrow,) = self.money((self.resident["escrow_account_id"], ledger.escrow(cert.cert_id)))
        need(escrow == STORM_CAP_CENTS, f"escrow holds {dollars(escrow)} {self.source} after Storm Mode, not $50")
        result = (f"escrow {dollars(self.escrow_cents)} → {dollars(escrow)} {self.source}, CERT v{before.cert_ver} "
                  f"→ v{cert.cert_ver} at $50")
        self.escrow_cents = escrow
        return result

    # 4 -----------------------------------------------------------------------------------------

    def offline_payment(self) -> str:
        self.policy = self.latest_policy()  # the highest POLICY the phones have verified
        now = int(time.time())
        mcert = self.mcerts[self.pharmacy.name]
        req = Req(mcert.merchant_id, PRICE_CENTS, crypto.random_nonce(), now + 120).signed(self.pharmacy.key)
        request_qr = qr({"mc": mcert.to_json(), "rq": req.to_json()})
        seen_mcert, seen_req = payer_check(request_qr, self.server_pub, self.wallet.cert, self.wallet.cum, now)
        pay_qr = qr(self.wallet.pay(self.maya.key, seen_mcert, seen_req, now).to_json())
        self.honest, result = receive(self.pharmacy, mcert, req, pay_qr, self.policy, self.server_pub, now)
        need(result.ok, f"the Pharmacy's phone shows red: {result.check} {result.reason}")
        t = self.honest.tag
        return (f"the Pharmacy's checks C1–C6 pass offline (green): {dollars(t.cum_cents)} of "
                f"{dollars(self.wallet.cert.cap_cents)} used, counter {t.counter}")

    # 5 -----------------------------------------------------------------------------------------

    def rollbacks(self) -> str:
        now = int(time.time())
        meet(self.pharmacy, self.maya, now)  # demo topology: Pharmacy ↔ Maya ↔ Gas Station (§10.6)
        meet(self.maya, self.gas, now)
        need(self.honest.tag.tag_hash in self.gas.items, "the Pharmacy's payment didn't reach the Gas Station")
        mcert = self.mcerts[self.gas.name]
        seen = []
        for mode, expected in (("reuse", rules.SAME_COUNTER), ("clever", rules.BROKEN_LINK)):
            self.wallet.roll_back(mode)
            req = Req(mcert.merchant_id, PRICE_CENTS, crypto.random_nonce(), now + 120).signed(self.gas.key)
            seen_mcert, seen_req = payer_check(qr({"mc": mcert.to_json(), "rq": req.to_json()}), self.server_pub,
                                               self.wallet.cert, self.wallet.cum, now)
            pay = self.wallet.pay(self.maya.key, seen_mcert, seen_req, now)
            _, result = receive(self.gas, mcert, req, qr(pay.to_json()), self.policy, self.server_pub, now)
            label = "Reuse the money" if mode == "reuse" else "Be clever"
            need(not result.ok and result.check == "C6" and result.rule == expected,
                 f"{label}: expected C6 {expected}, got {'green' if result.ok else f'{result.check} {result.reason}'}")
            fired = rules.rules_fired(result.conflict, pay.tag)
            if mode == "reuse":
                self.reuse = pay
            else:
                need(rules.TOTAL_BACKWARDS in fired, f"Be clever: the running total didn't go backwards ({fired})")
                self.clever = pay
            seen.append(f"{label} (counter {pay.tag.counter}) → C6 {' + '.join(fired)}")
        proofs = [i for i in self.gas.items.values() if i.kind == "PROOF"]
        need(len(proofs) == 2, f"the Gas Station built {len(proofs)} proofs, not 2")
        return "refused offline: " + "; ".join(seen)

    # 6 -----------------------------------------------------------------------------------------

    def upload(self) -> str:
        cert = self.wallet.cert
        policy_before = self.latest_policy().policy_ver
        items = list(self.gas.items.values())
        honest_item = self.gas.items[self.honest.tag.tag_hash]
        need(len(honest_item.path) == 3, f"the Pharmacy's payment came {len(honest_item.path) - 1} hops, not 2")
        out = self.post("/v1/sync", {"device_pub": b64u_encode(self.gas.pub), "items": [i.to_json() for i in items]},
                        self.gas)
        rcpt = Rcpt.from_json(out["rcpt"])
        need(rcpt.verify(self.server_pub), "the RCPT isn't signed by SERVER_PUB")
        missing = [i for i in items if i.id not in rcpt.item_ids]
        need(not missing, f"{len(missing)} of {len(items)} items not receipted ({', '.join(i.kind for i in missing)})")
        policy = Policy.from_json(out["policy"])
        need(policy.verify(self.server_pub) and policy.policy_ver > policy_before
             and cert.cert_id in policy.frozen_certs,
             f"no new POLICY freezing the cert (got v{policy.policy_ver}, had v{policy_before})")

        paths = self.get("/v1/relay/paths", limit=50)
        relay = next((p for p in paths if p["tag_hash"] == b64u_encode(self.honest.tag.tag_hash)), None)
        need(relay, "the payment isn't in GET /v1/relay/paths")
        names = [h["name"] for h in relay["path"]]
        need(relay["hops"] == 2 and names == [self.pharmacy.name, self.maya.name, self.gas.name],
             f"relay path {' → '.join(names)} ({relay['hops']} hops)")

        with self.pool.connection() as conn:
            payments = {bytes(r["tag_hash"]): r for r in all_rows(
                conn, "SELECT * FROM payments WHERE cert_id = %s", (cert.cert_id,))}
            moves = all_rows(conn, """SELECT o.status AS payout_status, o.source, o.amount_cents, n.txn_id,
                                             n.withdrawal_id, n.deposit_id
                                      FROM payouts o LEFT JOIN nessie_moves n USING (payout_id)
                                      WHERE o.tag_hash = ANY(%s)""", (list(payments),))
            frozen = scalar(conn, "SELECT status FROM cert_status WHERE cert_id = %s", (cert.cert_id,))
        p = payments.get(self.honest.tag.tag_hash)
        need(p and (p["status"], p["funded_escrow_cents"], p["funded_pool_cents"]) == ("settled", PRICE_CENTS, 0),
             f"the Pharmacy's payment is {p and p['status']}, not settled from escrow")
        refused = [payments.get(x.tag.tag_hash, {}).get("status") for x in (self.reuse, self.clever)]
        need(refused == ["refused_evidence"] * 2, f"the refused payments are {refused}, not refused_evidence")
        need(len(moves) == 1, f"{len(moves)} payouts, not one")
        move = moves[0]
        need(move["source"] == "escrow" and move["amount_cents"] == PRICE_CENTS, "the payout isn't $12 from escrow")
        pharmacy_account = self.shops[self.pharmacy.name]["nessie_account_id"]
        if self.nessie_on:
            need(move["payout_status"] == "executed" and move["withdrawal_id"] and move["deposit_id"],
                 f"the Nessie payout is {move['payout_status']} (queued: Nessie slow or down?)")
            desc = f"SC {move['txn_id']} "
            withdrawal = next((w for w in self.nessie.records(self.resident["escrow_account_id"], "withdrawals")
                               if w.get("_id") == move["withdrawal_id"]), None)
            deposit = next((d for d in self.nessie.records(pharmacy_account, "deposits")
                            if d.get("_id") == move["deposit_id"]), None)
            need(withdrawal and withdrawal["amount"] == PRICE_CENTS // 100 and withdrawal["description"].startswith(desc),
                 "Nessie has no matching $12 withdrawal on the escrow account")
            need(deposit and deposit["amount"] == PRICE_CENTS // 100 and deposit["description"].startswith(desc),
                 "Nessie has no matching $12 deposit on the Pharmacy's account")
        else:
            need(move["payout_status"] == "ledger_only", f"the payout is {move['payout_status']}, not ledger_only")
        escrow, shop = self.money((self.resident["escrow_account_id"], ledger.escrow(cert.cert_id)),
                                  (pharmacy_account, ledger.merchant(self.mcerts[self.pharmacy.name].merchant_id)))
        need((escrow, shop) == (self.escrow_cents - PRICE_CENTS, PRICE_CENTS),
             f"after settlement escrow holds {dollars(escrow)} and the Pharmacy {dollars(shop)} {self.source}")

        cases = [c for c in self.get("/v1/cases", limit=50) if c["cert_id"] == b64u_encode(cert.cert_id)]
        pair = {b64u_encode(self.honest.tag.tag_hash), b64u_encode(self.reuse.tag.tag_hash)}
        same = next((c for c in cases if c["rule"] == rules.SAME_COUNTER and {c["tag_a"], c["tag_b"]} == pair), None)
        need(same, f"no SAME_COUNTER case for the two payments (cases: {[c['rule'] for c in cases]})")
        need(same["detected_where"] == "offline", "the case isn't marked as found offline")
        need(frozen == "frozen", f"the cert is {frozen}, not frozen")
        self.case_id = same["case_id"]
        others = sorted(c["rule"] for c in cases if c is not same)
        pair_text = (f"withdrawal + deposit in Nessie, escrow {dollars(self.escrow_cents)} → {dollars(escrow)}, "
                     f"Pharmacy $0 → {dollars(shop)}" if self.nessie_on else f"ledger only, Pharmacy {dollars(shop)}")
        return (f"{len(items)} items, Pharmacy → Maya → Gas Station → server (2 hops); the $12 settled from escrow "
                f"({pair_text}); case #{self.case_id} SAME_COUNTER found offline"
                + (f" (+ {', '.join(others)})" if others else "") + "; "
                f"cert frozen in POLICY v{policy.policy_ver}")

    # 7 -----------------------------------------------------------------------------------------

    def proof(self) -> str:
        doc = self.get(f"/v1/proof/{self.case_id}")
        objs = {}
        for name, cls in (("cert", Cert), ("tag_a", Tag), ("tag_b", Tag)):
            shown = doc[name]
            obj = cls.from_json(shown["json"])
            need(shown["canonical"] == obj.canonical() and shown["digest"] == obj.digest().hex()
                 and shown["fields"] == obj.to_fields(), f"{name}: the text shown isn't what was signed")
            objs[name] = obj
        cert, a, b = objs["cert"], objs["tag_a"], objs["tag_b"]
        need(cert.verify(self.server_pub), "CERT not signed by the pinned SERVER_PUB")
        need(b64u_decode(doc["holder_pub"]) == cert.holder_pub == self.maya.pub, "holder_pub isn't the cert's")
        need(a.verify(cert.holder_pub) and b.verify(cert.holder_pub) and a.cert_id == b.cert_id == cert.cert_id,
             "the two tags aren't both signed by the cert's holder")
        need(doc["rule"] in rules.rules_fired(a, b), f"{doc['rule']} doesn't hold for the signed fields")
        need(rules.verify_proof(Proof(a, b, doc["rule"]), cert.holder_pub), "the PROOF doesn't verify")
        done = f"case #{self.case_id} {doc['rule']}: Python verifies the CERT (pinned key), both TAGs and the rule"
        if self.verify_bin is None or not self.verify_bin.is_file():
            return done + "; C++ stormcash-verify not built (cpp/build/verify), skipped"
        run = subprocess.run([str(self.verify_bin), "proof", "-", "--server-pub", self.server_pub.hex()],
                             input=json.dumps(doc), capture_output=True, text=True, timeout=20)
        need(run.returncode == 0, f"stormcash-verify exit {run.returncode}: "
                                  f"{(run.stdout.strip().splitlines() or [run.stderr.strip()])[-1][:120]}")
        return done + "; C++ stormcash-verify: proven (exit 0)"

    # 8 -----------------------------------------------------------------------------------------

    def town(self) -> str:
        with self.pool.connection() as conn:
            shops = scalar(conn, "SELECT count(*) FROM merchants WHERE simulated")
        need(shops, "no simulated town: POST /v1/demo/seed-town {\"seed\": 42}")
        flags = [f for f in self.get("/v1/flags", limit=500) if f.get("subject_name") == "Corner Store"]
        need(flags, f"{shops} simulated shops, but no Corner Store flag yet: let StormDesk triage the seeded town")
        droid = [f for f in flags if f.get("runner") == "droid"]
        need(droid, f"the Corner Store flag{'s are' if len(flags) > 1 else ' is'} the fake runner's (rules only), "
                    "not Droid's: run StormDesk on it before judging")
        flag = droid[0]  # newest first
        need(flag["status"] != "invalid" and flag["citations_valid"], f"Corner Store flag #{flag['flag_id']} is invalid")
        run = self.get(f"/v1/stormdesk/runs/{flag['run_id']}") if flag.get("run_id") else {}
        model = (run.get("transcript") or {}).get("model")
        verdict = (f"Corner Store flag #{flag['flag_id']}: {flag['kind']}, {flag['severity']}, propose "
                   f"{flag['proposed_action']}, {flag['status']} (Droid{', ' + model if model else ''})")
        review = flag.get("review") or {}
        if review:
            who = "Droid" if review.get("runner") == "droid" else "fake reviewer"
            verdict += f"; reviewer ({who}): {review.get('verdict', review.get('status'))}"
            if flag.get("agents_disagree"):
                verdict += ", agents disagree"
        else:
            verdict += "; no review"
        return f"{verdict}; {plural(shops, 'simulated shop')}"

    # 9 -----------------------------------------------------------------------------------------

    def cleanup(self) -> str:
        with self.pool.connection() as conn:
            mine = self._dry_run_runs(conn)
            runs = one(conn, "SELECT count(*) AS n, COALESCE(MAX(run_id), 0) AS top FROM stormdesk_runs")
        need(mine == 0, f"StormDesk ran {mine} time(s) on dry-run data: check the worker's dry-run filter")
        others = runs["n"] - self.runs_before[0]
        credits = (f"no StormDesk run on dry-run data (runs {self.runs_before[0]} → {runs['n']}"
                   + (f"; {others} started meanwhile, not by the dry run" if others else "") + ")")
        if self.keep:
            return f"kept everything (--keep); {credits}. POST /v1/demo/reset removes it"
        out = self.post("/v1/demo/reset", {})
        removed = out.get("dry_run_removed") or {}
        with self.pool.connection() as conn:
            left = scalar(conn, """SELECT (SELECT count(*) FROM residents WHERE starts_with(display_name, %s))
                                       + (SELECT count(*) FROM merchants WHERE starts_with(display_name, %s))
                                       + (SELECT count(*) FROM nessie_calls WHERE strpos(COALESCE(summary, ''), %s) > 0)""",
                          (DRY_RUN_PREFIX,) * 3)
            stray = scalar(conn, """SELECT (SELECT count(*) FROM tags WHERE cert_id = %s)
                                        + (SELECT count(*) FROM cert_status WHERE cert_id = %s)
                                        + (SELECT count(*) FROM cases WHERE cert_id = %s)""",
                           (self.wallet.cert.cert_id,) * 3) if hasattr(self, "wallet") else 0
            unbalanced = ledger.unbalanced_txns(conn)
            frozen = all_rows(conn, "SELECT cert_id FROM cert_status WHERE status = 'frozen'")
            runs_now = scalar(conn, "SELECT count(*) FROM stormdesk_runs")
        need(left == 0 and stray == 0, f"{left + stray} dry-run rows still in the database after the reset")
        need(not unbalanced, f"ledger unbalanced: {len(unbalanced)} transactions")
        policy = self.latest_policy()
        need(set(policy.frozen_certs) == {bytes(r["cert_id"]) for r in frozen}, "the latest POLICY isn't the reset's")
        need(runs_now == runs["n"], "the reset changed stormdesk_runs")
        real = ", ".join(f"{r['display_name']}'s cert reissued ($20)" for r in out.get("residents", [])) or \
            "no real resident registered yet"
        return (f"removed {plural(removed.get('residents', 0), 'resident')}, {plural(removed.get('shops', 0), 'shop')}, "
                f"{plural(removed.get('tags', 0), 'tag')}, {plural(removed.get('cases', 0), 'case')}; demo reset ({real}); "
                f"ledger balanced; {credits}")

    def _dry_run_runs(self, conn) -> int:
        return scalar(conn, """SELECT count(*) FROM stormdesk_runs r WHERE
            r.case_id IN (SELECT c.case_id FROM cases c JOIN certificates ce ON ce.cert_id = c.cert_id
                          JOIN residents d ON d.resident_id = ce.resident_id WHERE starts_with(d.display_name, %(p)s))
            OR r.candidate_id IN (SELECT k.candidate_id FROM candidates k WHERE k.subject_id IN (
                SELECT encode(ce.cert_id, 'hex') FROM certificates ce JOIN residents d USING (resident_id)
                WHERE starts_with(d.display_name, %(p)s)
                UNION SELECT encode(merchant_id, 'hex') FROM merchants WHERE starts_with(display_name, %(p)s)))
            OR r.merchant_id IN (SELECT merchant_id FROM merchants WHERE starts_with(display_name, %(p)s))""",
                      {"p": DRY_RUN_PREFIX})

    # Runner ------------------------------------------------------------------------------------

    def steps(self) -> list[Step]:
        return [
            Step("Server up, schema current, key = SERVER_PUB, StormDesk safe", self.preflight, ()),
            Step("Register Dry-run Maya and two shops", self.register, (1,)),
            Step("Storm Mode: escrow $20 → $50", self.storm_mode, (2,)),
            Step("Offline payment of $12 passes C1–C6", self.offline_payment, (3,)),
            Step("Judge mode rollbacks refused by C6", self.rollbacks, (4,)),
            Step("Upload through the 2-hop path", self.upload, (5,)),
            Step("Proof verifies", self.proof, (6,)),
            Step("Seeded town: Corner Store flag", self.town, (1,)),
            Step("Clean up and demo reset", self.cleanup, (1,)),
        ]

    def run(self) -> bool:
        started = time.monotonic()
        color = hasattr(self.out, "isatty") and self.out.isatty()
        marks = {True: "\033[32m✓\033[0m" if color else "✓", False: "\033[31m✗\033[0m" if color else "✗"}
        self.say(f"StormCash demo dry run → {self.http.base_url}  (test identities {self.maya.name}, "
                 f"{self.pharmacy.name}, {self.gas.name}; never the real Maya's key)")
        passed: dict[int, bool] = {}
        for n, step in enumerate(self.steps(), 1):
            blocked = [d for d in step.needs if not passed.get(d)]
            t0 = time.monotonic()
            if blocked:
                ok, reason = False, f"not run: step {blocked[0]} failed"
                if not passed.get(1):
                    ok, reason = None, "not run: nothing was written"
            else:
                try:
                    ok, reason = True, step.run()
                except Failed as exc:
                    ok, reason = False, str(exc)
                except Exception as exc:  # report it as this beat's failure and go on
                    ok, reason = False, f"{type(exc).__name__}: {exc}"
            passed[n] = bool(ok)
            elapsed = time.monotonic() - t0
            self.results.append((n, step.title, ok, reason, elapsed))
            mark = "–" if ok is None else marks[ok]
            self.say(f"{n:>2} {mark} {step.title} ({elapsed:.1f} s): {reason}")
        total = time.monotonic() - started
        failed = [r for r in self.results if not r[2]]
        if failed:
            self.say(f"{len(failed)} of {len(self.results)} steps did not pass ({total:.1f} s).")
        else:
            self.say(f"All {len(self.results)} steps passed in {total:.1f} s.")
        return not failed

    def say(self, line: str) -> None:
        print(line, file=self.out, flush=True)


def load_env(env_file: Path = SERVER_DIR / ".env") -> dict[str, str]:
    """server/.env, then real environment variables over it (as config.load_settings reads them)."""
    env = {k: v for k, v in dotenv_values(env_file).items() if v is not None} if env_file.exists() else {}
    env.update(os.environ)
    return env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m stormcash.dryrun", description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default="http://localhost:8000", help="the server to check")
    parser.add_argument("--keep", action="store_true", help="skip the cleanup and the demo reset (debugging)")
    parser.add_argument("--server-pub", help="the server key the phones pin, hex or base64url (default: "
                                             "SERVER_PUB_HEX from server/.env, else mobile/src/config.ts)")
    parser.add_argument("--verify-bin", type=Path, default=VERIFY_BIN, help="the C++ stormcash-verify binary")
    args = parser.parse_args(argv)

    env = load_env()
    mobile = mobile_server_pub()
    if args.server_pub:
        server_pub, source = parse_pub(args.server_pub), "--server-pub"
    elif env.get("SERVER_PUB_HEX"):
        server_pub, source = parse_pub(env["SERVER_PUB_HEX"]), "SERVER_PUB_HEX in server/.env"
    elif mobile is not None:
        server_pub, source = mobile, "mobile/src/config.ts"
    else:
        print("No SERVER_PUB: pass --server-pub, or set SERVER_PUB_HEX in server/.env", file=sys.stderr)
        return 2
    if not env.get("DATABASE_URL"):
        print("DATABASE_URL isn't set (server/.env): the dry run checks the server's database", file=sys.stderr)
        return 2
    nessie = None
    if env.get("NESSIE_API_KEY"):
        nessie = NessieReader(env.get("NESSIE_BASE_URL") or "https://api.nessieisreal.com", env["NESSIE_API_KEY"])
    pool = make_pool(env["DATABASE_URL"], min_size=1, max_size=2)
    try:
        with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=60) as http:
            ok = DryRun(http, pool, server_pub=server_pub, server_pub_source=source, nessie=nessie,
                        verify_bin=args.verify_bin, keep=args.keep, mobile_pub=mobile).run()
    finally:
        pool.close()
        if nessie is not None:
            nessie.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
