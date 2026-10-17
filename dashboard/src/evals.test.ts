// The Evals tab's helpers against the real saved rules-only run (chalk/evals/results).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { evalsTakeaway, METRICS, pct, scenarioCell, trapsRight, type EvalRun } from "./evals.ts";

const rules: EvalRun = JSON.parse(
  readFileSync(new URL("../../chalk/evals/results/20261017T023627Z-rules_only.json", import.meta.url), "utf8"),
);

test("the comparison rows read the run's own numbers", () => {
  const cells = Object.fromEntries(METRICS.map((m) => [m.label, m.cell(rules)]));
  assert.equal(cells["Real cases caught"], "21 / 21 (100%)");
  assert.equal(cells["Honest cases flagged"], "27 / 27 (100%)");
  assert.equal(cells["When it flags a quiet shop, how often it's right"], "9 / 20 (45%)");
  assert.equal(cells["Answers that only cite real records"], "n/a (cites nothing)");
  assert.deepEqual(cells["Pool money held back from colluding shops"], { cents: 18000, of: 18000 });
  assert.deepEqual(cells["Pool money held back from honest shops"], { cents: 22689 });
  assert.equal(cells["Cases with no answer · errors"], "0 · 0");
});

test("scenarios and traps", () => {
  const by = Object.fromEntries(rules.per_scenario.map((s) => [s.scenario, s]));
  assert.equal(scenarioCell(by.colluder), "caught 9 / 9");
  assert.equal(scenarioCell(by.trap_stockup), "left alone 0 / 12");
  assert.equal(scenarioCell(undefined), null);
  assert.equal(trapsRight(rules).length, 0); // the baseline flags every candidate
  const fixed = { ...rules, rows: rules.rows.map((r) => ({ ...r, scores: { ...r.scores, "no-false-flag": 1 } })) };
  assert.equal(trapsRight(fixed).length, rules.dataset.honest_rows); // only honest rows count, never real ones
  assert.equal(pct(null), "n/a");
  assert.equal(pct(0.4286), "43%");
});

test("the takeaway reads the scored runs' own counts", () => {
  const desk: EvalRun = {
    ...rules,
    metrics: { ...rules.metrics, honest_flagged: { flagged: 0, total: 27, false_flag_rate: 0 }, real_caught: { caught: 15, total: 21, recall: 0.71 } },
  };
  assert.equal(evalsTakeaway(rules, desk, true),
    "On towns it never saw, rules alone flagged all 27 honest cases; StormDesk flagged none of them and caught 15 of 21 real ones.");
  assert.match(evalsTakeaway(rules, null, false) ?? "", /^On the main dataset, rules alone caught 21 of 21 real cases .* No StormDesk run yet\.$/);
  assert.equal(evalsTakeaway(null, null, true), null);
});
