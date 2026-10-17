// The reconciliation panel's wording: only what the server computed, and an
// unreadable account is an error line, never a number.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  bankPill,
  itemsOf,
  openingNote,
  pairsLine,
  reconciledLine,
  signedUsd,
  simulatedNote,
  unreachable,
  usd,
  type ReconcileAccount,
  type Reconciliation,
} from "./reconcile.ts";

const pool: ReconcileAccount = {
  key: "pool", label: "Guarantee Pool", kind: "pool", nessie_account_id: "68f0", status: "difference", error: null,
  fetched_at: 1792260144,
  opening: { cents: 100000, source: "nessie", call_id: null, at: null, nessie_cents: 100000 },
  ledger_cents: -18359, simulated: { cents: -18359, txns: 11, label: "ledger only, never sent to Nessie" },
  expected_cents: 100000, nessie_cents: 99600, difference_cents: -400,
  records: { deposits: 0, withdrawals: 1, linked: 1, unlinked: 0, not_completed: 0 },
  by_kind: [{ kind: "not_in_ledger", label: "In Nessie, not in our ledger", count: 1, cents: -400 }],
  items: [{ kind: "not_in_ledger", cents: -400, txn_id: "6ba75a41", text: "SC 6ba75a41… …" }], items_total: 1,
};

const checking: ReconcileAccount = {
  ...pool, key: "checking:1", label: "Maya Checking", kind: "checking", status: "reconciled", simulated: null,
  opening: { cents: 50000, source: "call_log", call_id: 12, at: 1792250000, nessie_cents: 50000 },
  difference_cents: 0, by_kind: [], items: [], items_total: 0,
};

const result = (accounts: ReconcileAccount[], extra: Partial<Reconciliation> = {}): Reconciliation => ({
  checked_at: 1792260144, ok: true, last_ok_at: 1792260144, nessie: { enabled: true, error: null }, accounts,
  pairs: { checked: 1, complete: 0, problems: [], problems_total: 1 },
  simulated_town: { label: "Simulated town: ledger only, never sent to Nessie", merchants: 38, merchant_cents: 1039462 },
  ...extra,
});

test("money is integer cents formatted once", () => {
  assert.equal(usd(1039462), "$10,394.62");
  assert.equal(usd(-400), "−$4.00");
  assert.equal(signedUsd(400), "+$4.00");
  assert.equal(signedUsd(0), "$0.00");
});

test("each account says it matches, its difference and why, or why it has no number", () => {
  assert.deepEqual(bankPill(checking), { tone: "ok", text: "Matches" });
  assert.deepEqual(bankPill(pool), { tone: "diff", text: "−$4.00 · In Nessie, not in our ledger" });
  assert.equal(bankPill({ ...pool, by_kind: [] }).text, "−$4.00 · Unexplained");
  assert.equal(bankPill({ ...pool, status: "error", error: "GET /accounts: ConnectTimeout" }).text, "Nessie unreachable");
  assert.equal(bankPill({ ...pool, status: "no_nessie_account" }).text, "Ledger only");
});

test("the reconciled line counts only accounts that were read", () => {
  assert.deepEqual(reconciledLine(result([checking, pool])), {
    tone: "diff",
    text: "Reconciled with Nessie, 1 of 2 accounts · 1 with a difference",
  });
  assert.deepEqual(reconciledLine(result([checking])), { tone: "ok", text: "Reconciled with Nessie, 1 of 1 account" });
  const down = { ...pool, status: "error" as const };
  assert.deepEqual(reconciledLine(result([checking, down])), {
    tone: "error",
    text: "Reconciled with Nessie, 1 of 1 account · 1 unreadable",
  });
  assert.equal(reconciledLine(result([down])).text, "Nessie unreachable: nothing could be checked");
  assert.equal(reconciledLine(result([], { nessie: { enabled: false, error: null } })).tone, "off");
});

test("the opening says where each side's number comes from", () => {
  assert.equal(
    openingNote(checking.opening!),
    "Nessie keeps $500.00 as the account's fixed opening balance; our call log #12 opened it at $500.00 ✓. " +
      "The ledger books movements only.",
  );
  assert.match(openingNote(pool.opening!), /no record of the opening, so it is taken from Nessie/);
  assert.match(openingNote({ ...checking.opening!, source: "rule", nessie_cents: 40000 }), /opens this kind of account at \$500\.00\. /);
});

test("simulated money is ledger only, not a difference", () => {
  assert.equal(simulatedNote(pool.simulated!), "−$183.59 in 11 simulated transactions: ledger only, never sent to Nessie");
});

test("pairs and outages are worded from the server's counts", () => {
  assert.equal(pairsLine({ checked: 0, complete: 0, problems: [], problems_total: 0 }).tone, "off");
  assert.equal(
    pairsLine({ checked: 3, complete: 3, problems: [], problems_total: 0 }).text,
    "3 of 3 SC pairs complete (one withdrawal + one deposit) and matching the ledger ✓",
  );
  const clock = (t: number) => `t=${t}`;
  assert.equal(unreachable(result([checking]), clock), null);
  assert.equal(
    unreachable(result([], { ok: false, last_ok_at: 1792260000, nessie: { enabled: true, error: "ConnectTimeout" } }), clock),
    "Capital One Nessie can't be read right now (ConnectTimeout). Last successful check: t=1792260000.",
  );
  assert.match(unreachable(result([], { ok: false, last_ok_at: null }), clock) ?? "", /No successful check since/);
});

test("items per kind keep the server's total", () => {
  const many = { ...pool, by_kind: [{ ...pool.by_kind![0], count: 60 }], items: Array(50).fill(pool.items![0]) };
  const { shown, more } = itemsOf(many, "not_in_ledger");
  assert.equal(shown.length, 3);
  assert.equal(more, 57);
  assert.deepEqual(itemsOf(checking, "queued"), { shown: [], more: 0 });
});
