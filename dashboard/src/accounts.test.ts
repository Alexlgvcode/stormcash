// The Accounts tab's wording: account kind and owner from the card, and the
// Nessie call summary split into a description and its amount.
import assert from "node:assert/strict";
import { test } from "node:test";
import { accountAndOwner, callLine, callStatus } from "./accounts.ts";

test("account and owner follow spec §11.4's mapping", () => {
  assert.deepEqual(accountAndOwner({ label: "Maya Checking", kind: "checking" }), { account: "Checking", owner: "Maya" });
  assert.deepEqual(accountAndOwner({ label: "Dry-run Maya Escrow", kind: "escrow" }), {
    account: "StormCash escrow",
    owner: "Dry-run Maya",
  });
  assert.deepEqual(accountAndOwner({ label: "Gas Station", kind: "merchant" }), {
    account: "Merchant account",
    owner: "Gas Station",
  });
  assert.deepEqual(accountAndOwner({ label: "Guarantee Pool", kind: "pool" }), {
    account: "Guarantee pool",
    owner: "StormCash Operator",
  });
});

test("a call's amount moves to its own column", () => {
  const call = (summary: string | null, path = "/accounts/x/withdrawals") => callLine({ method: "POST", path, summary });
  assert.deepEqual(call("Maya escrow → Pharmacy, $12 (withdrawal)"), {
    description: "Maya escrow → Pharmacy (withdrawal)",
    cents: 1200,
  });
  assert.deepEqual(call("Storm Mode top-up, Maya checking → escrow, $30 (deposit)"), {
    description: "Storm Mode top-up, Maya checking → escrow (deposit)",
    cents: 3000,
  });
  assert.deepEqual(call("Open account Guarantee Pool, $1000"), { description: "Open account Guarantee Pool", cents: 100000 });
  assert.deepEqual(call("Create customer Maya Rivera"), { description: "Create customer Maya Rivera", cents: null });
  assert.deepEqual(call(null), { description: "POST withdrawal", cents: null });
});

test("call status words", () => {
  assert.deepEqual(callStatus(201), { ok: true, text: "completed" });
  assert.deepEqual(callStatus(503), { ok: false, text: "HTTP 503" });
  assert.deepEqual(callStatus(null), { ok: false, text: "timeout" });
});
