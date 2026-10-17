// Droid proposes a detector as a pull request (spec §14.7d, §18.5): the gap from
// the stored eval runs, and what an author run produced. Every number comes from
// a stored run or our server's re-run (§0 rule 3). No imports, so `npm test`
// runs this file directly.

export interface Counts {
  tp: number;
  fp: number;
  fn: number;
  tn: number;
  precision: number | null;
  recall: number | null;
}

export interface SplitMetrics {
  proposed: Counts;
  rules_only: Counts;
}

export interface DetectorProposal {
  name: string;
  kind: string;
  rationale: string;
  files_changed: string[];
  tests_passed: boolean;
  metrics: { dev: SplitMetrics; heldout: SplitMetrics };
  caveats: string[];
}

export interface Check {
  check: string;
  ok: boolean;
  detail: string;
}

export interface PullRequest {
  url?: string;
  number?: number | null;
  branch?: string;
  label?: string;
  error?: string;
  skipped?: string;
}

export interface EvalReport {
  metrics: { dev: SplitMetrics; heldout: SplitMetrics };
  data: Record<"dev" | "heldout", { seeds: number[]; rows: number; positives: number; sha256: string }>;
  detector: { name: string; kind: string; sha256: string };
  evaluator: string;
}

export interface AuthorTranscript {
  runner: string;
  gap: string;
  kind: string;
  examples: { row_id: string; note: string | null }[];
  steps?: { index: number; tool: string; input_summary: string; ok: boolean | null }[];
  model?: string | null;
  model_requested?: string | null;
  usage?: { factory_credits?: number; input_tokens?: number; output_tokens?: number; cache_read_tokens?: number } | null;
  permission_denials?: { tool: string | null; target: string | null; reason: string }[];
  lab_runs?: { cmd: string; name: string; exit_code: number; duration_s?: number }[];
  verified?: { ok: boolean; checks: Check[]; files: Record<string, string>; name: string | null; eval: EvalReport | null } | null;
  pull_request?: PullRequest | null;
  stopped_at_credit_cap?: boolean;
  sandbox?: { base_ref: string; base_sha: string; os_sandbox: boolean };
  duration_s?: number;
  error?: string | null;
}

export interface AuthorRun {
  run_id: number;
  job: string;
  runner: string;
  status: string;
  output: DetectorProposal | null;
  error: string | null;
  started_at: number;
  finished_at: number | null;
  transcript?: AuthorTranscript;
}

export interface AuthorState {
  enabled: boolean;
  reasons: string[];
  max_credits: number;
  base_ref: string;
  model: string;
  budget: { test: number; eval: number };
  running: boolean;
  runs: { run_id: number; status: string; kind: string | null; finished_at: number | null }[];
}

interface Row {
  row_id: string;
  kind: string;
  label_kind: string;
  honest_subject: boolean;
  output_kind: string | null;
}

export interface Gap {
  kind: string;
  dev: { caught: number; total: number } | null;
  heldout: { caught: number; total: number } | null;
  /** Dev rows StormDesk got wrong for this kind: real cases it missed, then honest ones it flagged. */
  examples: string[];
}

function caught(kind: string, rows: Row[] | undefined): { caught: number; total: number } | null {
  if (!rows) return null;
  const real = rows.filter((r) => r.label_kind === kind);
  return real.length ? { caught: real.filter((r) => r.output_kind === kind).length, total: real.length } : null;
}

/** Where StormDesk gets a kind wrong, from its stored dev and held-out eval runs. Held-out rows are never examples. */
export function gap(kind: string, dev: { rows: Row[] } | null, heldout: { rows: Row[] } | null): Gap {
  const rows = dev?.rows ?? [];
  const missed = rows.filter((r) => r.label_kind === kind && r.output_kind !== kind).map((r) => r.row_id);
  const falseFlags = rows.filter((r) => r.kind === kind && r.honest_subject && r.output_kind === kind).map((r) => r.row_id);
  return { kind, dev: caught(kind, dev?.rows), heldout: caught(kind, heldout?.rows), examples: [...missed, ...falseFlags].slice(0, 10) };
}

export function ratio(c: { caught: number; total: number } | null): string {
  return c ? `${c.caught} of ${c.total}` : "no run";
}

export function num(x: number | null | undefined): string {
  return x == null ? "n/a" : x.toFixed(2);
}

export function counts(c: Counts): string {
  return `${c.tp} / ${c.fp} / ${c.fn} / ${c.tn}`;
}

export const PHASE_LABEL: Record<string, string> = {
  sandbox: "Creating the sandbox worktree",
  droid: "Droid is writing the detector",
  verify: "Our server is re-running the tests and the eval",
  pull_request: "Our server is opening the pull request",
  done: "Done",
};

/** One line on what happened to a finished run. */
export function verdictLine(run: AuthorRun): string {
  const pr = run.transcript?.pull_request;
  if (run.status === "running") return "Running";
  if (run.status === "failed") return run.transcript?.stopped_at_credit_cap ? "Stopped at the credit cap" : "Failed";
  if (run.status === "invalid") return "Re-run rejected: no pull request";
  if (pr?.number) return `Pull request #${pr.number} opened for review`;
  if (pr?.error) return "Re-run matched; the pull request failed";
  if (pr?.skipped) return "Re-run matched; no pull request (not a Droid run)";
  return "Re-run matched";
}

export const CHECK_LABEL: Record<string, string> = {
  files: "Only the two allowlisted files changed",
  pure_detector: "Pure detector (no I/O, no imports)",
  no_secrets: "No secret values in the files",
  tests_rerun: "Tests pass on our re-run",
  eval_rerun: "Eval runs on our re-run",
  claims_match: "Droid's claims match our re-run",
};
