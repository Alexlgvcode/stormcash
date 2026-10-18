// The Overview's numbers: the mode from the Nessie log, and the money states as
// plain sums of what the server sent, real phones and simulated town apart.
import assert from "node:assert/strict";
import { test } from "node:test";
import { ago, modeFromCalls, phoneMoney, townMoney } from "./overview.ts";

test("the newer of top-up and refund says the mode", () => {
  const lock = { summary: "Lock escrow, Maya checking → escrow, $20 (deposit)", created_at: 100 };
  const up = { summary: "Storm Mode top-up, Maya checking → escrow, $30 (deposit)", created_at: 200 };
  const close = { summary: "Refund on close, Maya escrow → checking, $38 (deposit)", created_at: 300 };
  assert.equal(modeFromCalls([]).mode, "unknown");
  assert.equal(modeFromCalls([lock]).mode, "normal");
  assert.deepEqual(modeFromCalls([up, lock]).mode, "storm");
  assert.equal(modeFromCalls([up, lock]).at, 200);
  assert.equal(modeFromCalls([close, up, lock]).mode, "normal");
  assert.equal(modeFromCalls([{ ...up, created_at: 400 }, close, lock]).mode, "storm");
});

test("phone money counts only real shops' payments, by status", () => {
  const shops = [{ merchant_id: "p", simulated: false }, { merchant_id: "s", simulated: true }];
  const payments = [
    { tag_hash: "1", merchant_id: "p", status: "settled", amount_cents: 1200 },
    { tag_hash: "2", merchant_id: "p", status: "refused_evidence", amount_cents: 1200 },
    { tag_hash: "3", merchant_id: "p", status: "pending", amount_cents: 500 },
    { tag_hash: "4", merchant_id: "s", status: "settled", amount_cents: 999 },
  ];
  const cards = [
    { kind: "escrow" as const, nessie_cents: 3800, ledger_cents: 3800 },
    { kind: "escrow" as const, nessie_cents: 2000, ledger_cents: 2000 },
    { kind: "merchant" as const, nessie_cents: 1200, ledger_cents: 1200 },
    { kind: "checking" as const, nessie_cents: 45000, ledger_cents: -5000 },
  ];
  const cases = [
    { simulated: false, exposure_cents: 1200, detected_where: "offline" as const },
    { simulated: true, exposure_cents: 861, detected_where: "server" as const },
  ];
  const m = phoneMoney(cards, payments, shops, cases);
  assert.deepEqual(m.escrow, { cents: 5800, accounts: 2 });
  assert.equal(m.allowance, 5300);
  assert.deepEqual(m.accepted, { cents: 1700, count: 2 });
  assert.deepEqual(m.unsettled, { cents: 500, count: 1 });
  assert.deepEqual(m.settled, { cents: 1200, count: 1 });
  assert.deepEqual(m.refused, { cents: 1200, count: 1 });
  assert.deepEqual(m.exposure, { cents: 1200, count: 1 });
  assert.equal(m.offlineCatches, 1);
  assert.equal(m.merchantsPaid, 1200);
});

test("an escrow Nessie couldn't read gives no number, not zero", () => {
  const m = phoneMoney([{ kind: "escrow", nessie_cents: null, ledger_cents: 2000 }], [], [], []);
  assert.equal(m.escrow.cents, null);
  assert.equal(m.allowance, null);
  assert.equal(m.merchantsPaid, null);
});

test("town money comes from the seeded run's stats and the ledger", () => {
  const t = townMoney({ escrow_cents: 16897, merchant_cents: 1039462 }, {
    seed: 42,
    summary: { payments: 841, accepted: 832, settled: 831, refused: { C2: 6, C6: 3 } },
    double_spends: { attempts: 19, refused_offline: 2, caught_at_settlement: 17, not_caught_by_end: 0 },
    mean_loss_per_cheater_cents: 1456,
  }, [{ simulated: true, exposure_cents: 861, detected_where: "server" }]);
  assert.equal(t.seed, 42);
  assert.equal(t.refused, 9);
  assert.equal(t.attempts, 19);
  assert.deepEqual(t.exposure, { cents: 861, count: 1 });
  assert.equal(townMoney({ escrow_cents: 0, merchant_cents: 0 }, null, []).payments, null);
});

test("ago", () => {
  assert.equal(ago(100, 130), "just now");
  assert.equal(ago(100, 100 + 5 * 60), "5 min ago");
  assert.equal(ago(100, 100 + 3 * 3600), "3 h ago");
  assert.equal(ago(100, 100 + 2 * 86400), "2 d ago");
});
