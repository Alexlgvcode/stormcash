// The Evals tab's helpers against the real saved rules-only run (chalk/evals/results).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { METRICS, pct, scenarioCell, trapsRight, type EvalRun } from "./evals.ts";

const rules: EvalRun = JSON.parse(
  readFileSync(new URL("../../chalk/evals/results/20261017T023627Z-rules_only.json", import.meta.url), "utf8"),
);

test("the comparison rows read the run's own numbers", () => {
  const cells = Object.fromEntries(METRICS.map((m) => [m.label, m.cell(rules)]));
  assert.equal(cells["Real cases caught"], "21 / 21 (100%)");
  assert.equal(cells["Honest subjects flagged"], "27 / 27 (100%)");
  assert.equal(cells["Precision · merchant_silence"], "9 / 20 (45%)");
  assert.equal(cells["Citations valid"], "n/a (cites nothing)");
  assert.deepEqual(cells["Pool money held at colluders"], { cents: 18000, of: 18000 });
  assert.deepEqual(cells["Pool money held from honest shops"], { cents: 22689 });
  assert.equal(cells["Rows without a flag · task errors"], "0 · 0");
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
