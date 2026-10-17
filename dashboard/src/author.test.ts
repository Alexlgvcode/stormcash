// The author panel's helpers (spec §14.7d): the gap from stored eval runs, and a run's one-line verdict.
import assert from "node:assert/strict";
import { test } from "node:test";
import { counts, gap, num, ratio, verdictLine, type AuthorRun } from "./author.ts";

const row = (row_id: string, label_kind: string, output_kind: string | null, honest = false) =>
  ({ row_id, kind: "region_dark", label_kind, honest_subject: honest, output_kind });

test("the gap counts real cases caught and offers only dev rows as examples", () => {
  const dev = { rows: [row("7:8", "region_dark", "none"), row("42:10", "region_dark", "region_dark"),
    row("42:9", "none", "region_dark", true), row("99:8", "none", "none", true)] };
  const heldout = { rows: [row("1:11", "region_dark", "none"), row("2:9", "region_dark", "none")] };
  const g = gap("region_dark", dev, heldout);
  assert.deepEqual(g.dev, { caught: 1, total: 2 });
  assert.deepEqual(g.heldout, { caught: 0, total: 2 });
  assert.deepEqual(g.examples, ["7:8", "42:9"]);
  assert.equal(ratio(g.heldout), "0 of 2");
  assert.equal(ratio(gap("region_dark", null, null).dev), "no run");
});

test("numbers are formatted, never invented", () => {
  assert.equal(num(null), "n/a");
  assert.equal(num(0.5556), "0.56");
  assert.equal(counts({ tp: 5, fp: 0, fn: 0, tn: 4, precision: 1, recall: 1 }), "5 / 0 / 0 / 4");
});

test("a run's verdict says whether a pull request was opened", () => {
  const run = (status: string, transcript: object): AuthorRun =>
    ({ run_id: 1, job: "author", runner: "droid", status, output: null, error: null, started_at: 0, finished_at: 1,
       transcript: { runner: "droid", gap: "", kind: "region_dark", examples: [], ...transcript } });
  assert.equal(verdictLine(run("succeeded", { pull_request: { number: 130 } })), "Pull request #130 opened for review");
  assert.equal(verdictLine(run("invalid", {})), "Re-run rejected: no pull request");
  assert.equal(verdictLine(run("failed", { stopped_at_credit_cap: true })), "Stopped at the credit cap");
  assert.equal(verdictLine(run("succeeded", { pull_request: { skipped: "fake" } })),
    "Re-run matched; no pull request (not a Droid run)");
});
