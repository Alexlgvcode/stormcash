// The Droid tab's helpers: formatting only what the server counted, never a zero for "not recorded".
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  builtinCalls,
  credits,
  duration,
  guardrailCount,
  guardrailCoverage,
  modelText,
  outputText,
  promptText,
  rate,
  reviewVerdicts,
  visibleRuns,
  type ConsoleRun,
  type Guardrail,
} from "./droid.ts";

const base: ConsoleRun = {
  run_id: 88, job: "triage", subject: "candidate #16 · merchant_silence · Corner Store", case_id: null,
  candidate_id: 16, runner: "droid", status: "succeeded", outcome: "valid", outcome_label: "Valid",
  verdict: "merchant_silence → hold_pool_payout", model: "claude-sonnet-5-5", model_requested: "claude-sonnet-5-5",
  prompt_version: 2, duration_ms: 44898, factory_credits: 70319, usage: null, tool_calls: 8, tool_errors: 0,
  other_calls: { ToolSearch: 1 }, citations_valid: true, missing_citations: 0, structured_output_retries: null,
  permission_denials: null, fallback_reason: null, reviewed_run_id: null, error: null, started_at: 1792245968,
  finished_at: 1792246013,
};

const guard = (count: number | null, recorded: number | null): Guardrail => ({
  key: "permission_denial", label: "Permission-handler denials", about: "", count, events: [], recorded_runs: recorded,
});

test("numbers are formatted, missing ones are a dash", () => {
  assert.equal(credits(70319), "70,319");
  assert.equal(credits(null), "—");
  assert.equal(duration(44898), "45 s");
  assert.equal(duration(70), "0.1 s");
  assert.equal(duration(125_000), "2 min 05 s");
  assert.equal(duration(null), "—");
});

test("a success rate needs Droid runs", () => {
  assert.equal(rate({ valid: 1, droid_runs: 2, success_rate: 0.5 }), "1 of 2 (50%)");
  assert.equal(rate({ valid: 0, droid_runs: 0, success_rate: null }), "no Droid runs yet");
});

test("an unrecorded guardrail is never zero", () => {
  assert.equal(guardrailCount(guard(null, 0)), "not recorded yet");
  assert.equal(guardrailCoverage(guard(null, 0), 2), "no stored run records it yet");
  assert.equal(guardrailCount(guard(0, 2)), "0");
  assert.equal(guardrailCoverage(guard(0, 2), 2), null);
  assert.equal(guardrailCoverage(guard(1, 1), 3), "recorded on 1 of 3 Droid runs");
});

test("the model says when Factory switched it, and a fake run says rules only", () => {
  assert.equal(modelText(base), "claude-sonnet-5-5");
  assert.equal(modelText({ ...base, model: "droid-core" }), "droid-core (asked for claude-sonnet-5-5)");
  assert.equal(modelText({ ...base, model: null }), "model not recorded");
  assert.equal(modelText({ ...base, runner: "fake" }), "rules only");
  assert.equal(modelText({ ...base, runner: "pending" }), "runner not chosen yet");
  assert.equal(builtinCalls({ ToolSearch: 2 }), "ToolSearch × 2");
  assert.equal(builtinCalls({}), null);
});

test("the table shows Droid's runs and fallbacks unless fake ones are asked for", () => {
  const runs: ConsoleRun[] = [
    base,
    { ...base, run_id: 87, runner: "fake", outcome: "fake" },
    { ...base, run_id: 86, runner: "fake", outcome: "fallback", fallback_reason: "model_usage_exhausted" },
    { ...base, run_id: 89, runner: "pending", outcome: "running" },
  ];
  assert.deepEqual(visibleRuns(runs, false).map((r) => r.run_id), [88, 86, 89]);
  assert.equal(visibleRuns(runs, true).length, 4);
});

test("reviews: verdict counts and reasons", () => {
  assert.equal(reviewVerdicts({}), null);
  assert.equal(reviewVerdicts({ agree: 3, disagree: 1 }), "agrees 3 · disagrees 1");
  assert.equal(outputText({ verdict: "disagree", reasons: ["Shop kept syncing", "One cheater only"] }),
    "• Shop kept syncing\n• One cheater only");
  assert.equal(outputText({ summary: "Corner Store went quiet" }), "Corner Store went quiet");
  assert.equal(outputText(null), null);
});

test("a review's prompt is the reviewer's", () => {
  assert.equal(promptText(base), "prompt v2");
  assert.equal(promptText({ job: "review", prompt_version: 1 }), "reviewer prompt v1");
  assert.equal(promptText({ job: "triage", prompt_version: null }), null);
});
