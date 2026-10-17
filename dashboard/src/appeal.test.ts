import assert from "node:assert/strict";
import { test } from "node:test";
import { heldBack, sessionSummary, sessionsOf, turnLabel, turnsByReply, type AppealTurn } from "./appeal.ts";

const base: AppealTurn = {
  run_id: 1, runner: "droid", status: "succeeded", session_id: "8c1f2a3b-0d4e-4f5a-9b6c-7d8e9f0a1b2c",
  citations_valid: true, model: "claude-sonnet-5-5", factory_credits: 12000, duration_s: 21.4, fallback_from_droid: null,
  mode: "session", flag_id: 16, in_message_id: 2, out_message_id: 3, reply_sent: true, session: "started", turn: 1,
  resume_error: null,
};

const thread: AppealTurn[] = [
  base,
  { ...base, run_id: 2, in_message_id: 4, out_message_id: 5, session: "resumed", turn: 2, factory_credits: 8000 },
  { ...base, run_id: 3, in_message_id: 6, out_message_id: 7, session: "resumed", turn: 3, factory_credits: 9500,
    status: "invalid", citations_valid: false, reply_sent: false },
];

test("one Droid session for the whole thread", () => {
  assert.deepEqual(sessionsOf(thread), [{ session_id: base.session_id, turns: 3, credits: 29500 }]);
  assert.equal(sessionSummary(thread), "One Droid session · 3 turns · 29,500 credits");
});

test("each reply says which turn of which session wrote it", () => {
  assert.equal(turnLabel(thread[0]), "Droid · turn 1 · new session 8c1f2a3b · 12,000 credits");
  assert.equal(turnLabel(thread[1]), "Droid · turn 2 · same Droid session 8c1f2a3b · 8,000 credits");
  assert.equal(turnsByReply(thread).get(5)?.turn, 2);
});

test("a restarted session and the per-message fallback are named as such", () => {
  const restarted = { ...base, session_id: "ffee0011-2233", session: "restarted" as const, turn: 1, resume_error: "SessionNotFoundError" };
  assert.match(turnLabel(restarted), /new session ffee0011 from the stored thread/);
  assert.equal(sessionSummary([base, restarted]), "2 Droid sessions · 2 turns · 24,000 credits");
  assert.equal(turnLabel({ ...base, mode: "per_message" }), "Droid · one run for this message · 12,000 credits");
});

test("a fake-runner turn is labelled and never counted as a Droid session", () => {
  const fake = { ...base, runner: "fake", session_id: "fake-abc", session: null, turn: null, factory_credits: null, reply_sent: false };
  assert.equal(turnLabel(fake), "Fake runner · rules only");
  assert.equal(turnLabel({ ...fake, fallback_from_droid: "model_usage_exhausted" }), "Fake runner · rules only (Droid couldn't run)");
  assert.equal(sessionSummary([fake]), null);
  assert.equal(heldBack(fake), null);
});

test("a reply the citation check held back says why", () => {
  assert.equal(heldBack(thread[2]), "Droid's reply was held back: it cited a record that doesn't exist");
  assert.equal(heldBack(thread[1]), null);
});
