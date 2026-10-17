// The flag panel's reading of a review (spec §14.7b): only a valid agent review counts.
import assert from "node:assert/strict";
import { test } from "node:test";
import { reviewVerdict, suggestion, type FlagReview } from "./review.ts";

const base: FlagReview = {
  run_id: 90, runner: "droid", status: "succeeded", verdict: "agree", reasons: ["r"], evidence_ids: ["ab"],
  citations_valid: true, missing_citations: [], error: null, model: "claude-sonnet-5-5",
  usage: { factory_credits: 41000 },
};

test("an agent's verdict counts", () => {
  assert.deepEqual(reviewVerdict(base), { label: "Reviewer agrees", tone: "agree", counted: true, note: null });
  assert.equal(reviewVerdict({ ...base, verdict: "disagree" }).label, "Reviewer disagrees");
  assert.equal(reviewVerdict({ ...base, verdict: "insufficient_evidence" }).label, "Reviewer: not enough evidence");
  assert.equal(reviewVerdict({ ...base, verdict: "insufficient_evidence" }).tone, "disagree");
});

test("the fake reviewer is labelled and never counts against a flag", () => {
  const fake = reviewVerdict({ ...base, runner: "fake", verdict: "disagree" });
  assert.equal(fake.label, "Fake reviewer (rules only) disagrees");
  assert.equal(fake.counted, false);
  assert.match(fake.note ?? "", /Not counted/);
  assert.equal(reviewVerdict({ ...base, runner: "fake" }).note, null);
});

test("an invalid or failed review isn't a verdict", () => {
  const invalid = reviewVerdict({ ...base, status: "invalid", verdict: "disagree", citations_valid: false });
  assert.equal(invalid.label, "Reviewer cited a record that doesn't exist");
  assert.equal(invalid.counted, false);
  assert.equal(reviewVerdict({ ...base, status: "failed", verdict: null }).label, "Reviewer gave no answer");
});

test("what the reviewer would do instead, only when it doesn't agree", () => {
  const kinds = { merchant_silence: "Shop went quiet" };
  const actions = { hold_pool_payout: "Hold guarantee-pool payouts" };
  const disagree: FlagReview = { ...base, verdict: "disagree", suggested_kind: "merchant_silence",
    suggested_action: "hold_pool_payout", suggested_severity: "urgent" };
  assert.equal(suggestion(disagree, kinds, actions), "Suggests: Shop went quiet · Hold guarantee-pool payouts · urgent");
  assert.equal(suggestion({ ...disagree, verdict: "agree" }, kinds, actions), null);
  assert.equal(suggestion({ ...base, verdict: "insufficient_evidence" }, kinds, actions), null);
});
