// The Cases tab's plain words, from the server's fields only.
import assert from "node:assert/strict";
import { test } from "node:test";
import { caseTitle, casesTakeaway, conflictSentence, plainChecks, type CaseRow } from "./cases.ts";

const pay = (merchant: string, status: string, amount = 861, counter = 2) =>
  ({ merchant, status, amount_cents: amount, counter, simulated: true });
const base: CaseRow = { case_id: 7, rule: "BROKEN_LINK", detected_where: "offline", exposure_cents: 861 };

test("a case is titled as what happened", () => {
  assert.equal(caseTitle({ ...base, payment_a: pay("Swannanoa Diner", "settled", 861, 1), payment_b: pay("Swannanoa Bakery", "refused_evidence") }),
    "Swannanoa Bakery refused $8.61: the wallet was rolled back");
  assert.equal(caseTitle({ ...base, rule: "SAME_COUNTER", detected_where: "server",
    payment_a: pay("Corner Store", "settled", 3500, 3), payment_b: pay("Downtown Shelter", "settled", 3500, 3) }),
    "$35.00 spent twice at Corner Store and Downtown Shelter: the same payment number was used twice");
  assert.equal(caseTitle({ ...base, rule: "MERCHANT_KNEW", merchant: "Corner Store", payment_b: pay("Corner Store", "denied_knowing", 3000) }),
    "Corner Store accepted $30.00 it knew was already spent");
  assert.equal(caseTitle({ ...base, rule: "LOG_TAMPER" }), "A device's signed log was altered");
  assert.equal(caseTitle({ ...base, rule: "TOTAL_BACKWARDS" }), "$8.61 spent twice: a payment number was skipped");
});

test("the conflict is one plain sentence", () => {
  const a = { counter: 4, amount_cents: 1200, cum_cents: 1200 };
  assert.equal(conflictSentence("SAME_COUNTER", a, { ...a }), "Both payments use payment number 4: an honest wallet uses each number once.");
  assert.equal(conflictSentence("BROKEN_LINK", a, { ...a, counter: 5 }),
    "Payment 5 should continue from payment 4, but points to a different payment.");
  assert.equal(conflictSentence("TOTAL_BACKWARDS", a, { counter: 6, amount_cents: 500, cum_cents: 1500 }),
    "Payment 6 says $10.00 was spent before it, but payment 4 had already brought the total to $12.00.");
  assert.equal(conflictSentence("", a, a), null);
  assert.match(conflictSentence("OVER_CAP", { ...a, cum_cents: 6000 }) ?? "", /reaches \$60\.00/);
});

test("the takeaway counts real and simulated cases", () => {
  assert.equal(casesTakeaway([{ simulated: false }, ...Array(58).fill({ simulated: true })]),
    "1 proven case from your phones, 58 from the simulated town.");
  assert.equal(casesTakeaway([{ simulated: true }]), "No proven cases from your phones yet, 1 from the simulated town.");
});

test("the browser's checks drop our object names", () => {
  const labels = plainChecks([
    { label: "CERT: the signed text matches the fields shown" },
    { label: "CERT: signature is valid for the StormCash server key 028b27e6…" },
    { label: "TAG: the signed text matches the fields shown" },
    { label: "TAG: signature is valid for the wallet key in the certificate" },
    { label: "TAG: the signed text matches the fields shown" },
    { label: "Counter 2 doesn't point back to counter 1" },
    { label: "Running total went backwards: 1100 < 1200 cents" },
  ]).map((c) => c.label);
  assert.deepEqual(labels, [
    "The bank's certificate: the signed text matches what's shown",
    "The bank's certificate: signed by the StormCash server (key 028b27e6…)",
    "Payment A: the signed text matches what's shown",
    "Payment A: signature is valid for the wallet key in the certificate",
    "Payment B: the signed text matches what's shown",
    "Payment 2 doesn't continue from payment 1",
    "Running total went backwards: $11.00 before, after $12.00 was already spent",
  ]);
});
