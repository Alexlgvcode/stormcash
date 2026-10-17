// The Evals tab's data (spec §18.5, §15.3): GET /v1/evals serves the saved Chalk
// runs (chalk/evals/results, format in chalk/evals/README.md). These helpers only
// read numbers out of a run; with no run they return null and the tab says so.
// No imports, so `npm test` runs this file directly.

export interface Ratio {
  caught: number;
  total: number;
  recall: number | null;
}

export interface EvalRow {
  row_id: string;
  seed: number;
  candidate_id: number;
  kind: string;
  subject_id: string;
  subject_name: string | null;
  label_scenario: string;
  label_kind: string;
  label_action: string;
  honest_subject: boolean;
  output_kind: string | null;
  output_severity: string | null;
  output_action: string | null;
  summary: string | null;
  reasoning: string | null;
  evidence_ids: string[];
  exposure_cents: number | null;
  runner: string | null;
  citations_valid: boolean | null;
  error: string | null;
  scores: Record<string, number | null>;
}

export interface ScenarioResult {
  scenario: string;
  rows: number;
  honest: boolean;
  label_kind: string;
  label_action: string;
  caught: number | null;
  dismissed: number | null;
  flagged: number;
  without_flag: number;
}

export interface EvalRun {
  file: string;
  runner: string;
  runner_label: string;
  is_agent_result: boolean;
  table_column: string | null;
  model: string | null;
  mode: string;
  timestamp: number;
  timestamp_iso: string;
  git_sha: string | null;
  chalk: {
    environment_id: string;
    suite: string;
    evaluation_id: string;
    evaluation_name: string;
    run_id: string;
    status: string;
    dashboard_url?: string | null;
  };
  dataset: {
    name: string;
    rows: number;
    honest_rows: number;
    seeds: number[];
    detector_misses: { seed: number; subject_id: string; name: string; scenario: string; expected_kind: string }[];
  };
  runners_seen: Record<string, number>;
  scorers: Record<string, { in_evaluation: boolean; mean: number | null; scored_rows: number; mean_honest_rows?: number }>;
  metrics: {
    real_caught: Ratio;
    colluders_caught: Ratio;
    honest_flagged: { flagged: number; total: number; false_flag_rate: number | null };
    precision_by_kind: Record<string, { flagged: number; correct: number; precision: number | null }>;
    citations_valid: { valid: number; checked: number; rate: number | null } | null;
    pool_cents: { at_colluders: number; held_correctly: number; held_from_honest_shops: number };
    rows_without_flag: number;
    task_errors: number;
    fallback_from_droid: number;
  };
  per_scenario: ScenarioResult[];
  rows: EvalRow[];
}

export interface RunSummary {
  file: string;
  runner: string;
  runner_label: string | null;
  mode: string | null;
  model: string | null;
  timestamp: number | null;
  chalk_run_id: string | null;
  evaluation_name: string | null;
  dataset_rows: number | null;
  reason: string;
}

export interface EvalsResponse {
  columns: { rules_only: EvalRun | null; stormdesk: EvalRun | null };
  other_runs: RunSummary[];
  errors: { file: string; error: string }[];
  runs_found: number;
}

export function pct(x: number | null | undefined): string {
  return x == null ? "n/a" : `${Math.round(x * 100)}%`;
}

function frac(n: number, d: number, rate: number | null): string {
  return `${n} / ${d} (${pct(rate)})`;
}

/** A table cell: text, or cents the tab formats as dollars. */
export type Cell = string | { cents: number; of?: number };

export interface Metric {
  label: string;
  hint: string;
  cell: (run: EvalRun) => Cell;
}

const KINDS = ["merchant_silence", "cap_drain", "region_dark"] as const;

export const METRICS: Metric[] = [
  {
    label: "Real cases caught",
    hint: "cheaters and dark regions flagged with the right kind and action",
    cell: (r) => frac(r.metrics.real_caught.caught, r.metrics.real_caught.total, r.metrics.real_caught.recall),
  },
  {
    label: "Colluding shops caught",
    hint: "the merchant_silence cheats",
    cell: (r) =>
      frac(r.metrics.colluders_caught.caught, r.metrics.colluders_caught.total, r.metrics.colluders_caught.recall),
  },
  {
    label: "Honest subjects flagged",
    hint: "false flags on the traps (lower is better)",
    cell: (r) =>
      frac(r.metrics.honest_flagged.flagged, r.metrics.honest_flagged.total, r.metrics.honest_flagged.false_flag_rate),
  },
  ...KINDS.map(
    (kind): Metric => ({
      label: `Precision · ${kind}`,
      hint: "of the flags of this kind, how many were right",
      cell: (r) => {
        const p = r.metrics.precision_by_kind[kind];
        return p ? frac(p.correct, p.flagged, p.precision) : "n/a";
      },
    }),
  ),
  {
    label: "Citations valid",
    hint: "every evidence id exists (§14.7)",
    cell: (r) => {
      const c = r.metrics.citations_valid;
      return c ? frac(c.valid, c.checked, c.rate) : "n/a (cites nothing)";
    },
  },
  {
    label: "Pool money held at colluders",
    hint: "pool money in the colluders' 6 h windows",
    cell: (r) => ({ cents: r.metrics.pool_cents.held_correctly, of: r.metrics.pool_cents.at_colluders }),
  },
  {
    label: "Pool money held from honest shops",
    hint: "lower is better",
    cell: (r) => ({ cents: r.metrics.pool_cents.held_from_honest_shops }),
  },
  {
    label: "Rows without a flag · task errors",
    hint: "counted as failures",
    cell: (r) => `${r.metrics.rows_without_flag} · ${r.metrics.task_errors}`,
  },
];

export const SCENARIO_LABEL: Record<string, string> = {
  colluder: "Colluding shop",
  stolen_phone: "Stolen phone",
  dark_region: "Dark region",
  trap_remote_shop: "Trap: remote shop",
  trap_victim_shop: "Trap: victim of a cheat",
  trap_stockup: "Trap: storm stock-up",
  trap_quiet_region: "Trap: quiet region",
  trap_clock_drift: "Trap: clock drift",
};

/** "caught 9 / 9" for real cases, "left alone 0 / 12" for traps. */
export function scenarioCell(s: ScenarioResult | undefined): string | null {
  if (!s) return null;
  const main = s.honest ? `left alone ${s.dismissed ?? 0} / ${s.rows}` : `caught ${s.caught ?? 0} / ${s.rows}`;
  return s.without_flag ? `${main} · ${s.without_flag} without a flag` : main;
}

/** The traps a run got right: honest subjects it didn't flag. */
export function trapsRight(run: EvalRun): EvalRow[] {
  return run.rows.filter((r) => r.honest_subject && r.scores["no-false-flag"] === 1);
}
