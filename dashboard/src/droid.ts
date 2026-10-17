// The Droid tab's data (spec §18.7): GET /v1/droid/console aggregates the stored
// StormDesk runs. These helpers only format what the server counted; a null
// count means "not recorded yet" and is never shown as zero (§0 rule 3).
// No imports, so `npm test` runs this file directly.

export type Outcome =
  | "valid"
  | "invalid_citation"
  | "rerun_rejected"
  | "structured_output_failed"
  | "fallback"
  | "fake"
  | "failed"
  | "running"
  | "unfinished";

export interface ConsoleUsage {
  input_tokens?: number;
  output_tokens?: number;
  cache_read_tokens?: number;
  cache_creation_tokens?: number;
  thinking_tokens?: number;
  factory_credits?: number;
}

export interface ConsoleRun {
  run_id: number;
  job: string;
  subject: string;
  case_id: number | null;
  candidate_id: number | null;
  runner: string;
  status: string;
  outcome: Outcome;
  outcome_label: string;
  verdict: string | null;
  model: string | null;
  model_requested: string | null;
  prompt_version: number | null;
  duration_ms: number | null;
  factory_credits: number | null;
  usage: ConsoleUsage | null;
  tool_calls: number;
  tool_errors: number;
  other_calls: Record<string, number>;
  citations_valid: boolean | null;
  missing_citations: number;
  structured_output_retries: number | null;
  permission_denials: number | null;
  fallback_reason: string | null;
  reviewed_run_id: number | null;
  appeal: AppealTurnInfo | null; // a respond run that is a turn of its appeal's Droid session (§17.2)
  session_id: string | null;
  error: string | null;
  started_at: number;
  finished_at: number | null;
}

export interface AppealTurnInfo {
  session: "started" | "resumed" | "restarted" | null;
  turn: number;
  session_id: string | null;
  resume_error: string | null;
}

/** Droid's appeal conversations (§17.2): one Droid session per appeal thread, resumed for each text. */
export interface AppealSessions {
  sessions: number;
  turns: number;
  resumed: number;
  restarted: number;
  longest: number;
}

export interface Totals {
  droid_runs: number;
  valid: number;
  success_rate: number | null;
  credits_total: number | null;
  credits_runs: number;
  mean_credits: number | null;
  mean_duration_ms: number | null;
  tool_calls: number;
  fake_runs: number;
  fallback_runs: number;
  running: number;
  unfinished: number;
  outcomes: Partial<Record<Outcome, number>>;
}

export interface GuardrailEvent {
  run_id: number;
  runner: string;
  job: string;
  detail: string | null;
}

export interface Guardrail {
  key: string;
  label: string;
  about: string;
  count: number | null;
  events: GuardrailEvent[];
  recorded_runs: number | null;
}

export interface Harness {
  mcp_server: string;
  read_only_tools: string[];
  builtin_tools_disabled: number;
  prompt_version: number;
  review_prompt_version: number | null;
  runner_setting: string;
  droid_available: boolean;
  model_setting: string;
  worker_on: boolean;
  author_on?: boolean; // Droid may propose detectors as PRs (§14.7d)
  cooldown_s: number;
  cooldown_reason: string | null;
}

export interface DroidConsole {
  as_of: number;
  run_count: number;
  review_verdicts: Partial<Record<"agree" | "disagree" | "insufficient_evidence", number>>;
  appeal_sessions?: AppealSessions; // absent on a server from before appeal sessions
  totals: Totals;
  by_job: (Totals & { job: string })[];
  guardrails: Guardrail[];
  builtin_calls_seen: Record<string, number>;
  runs: ConsoleRun[];
  harness: Harness;
}

/** A stored run with its transcript (GET /v1/stormdesk/runs/{id}). */
export interface RunDetail {
  run_id: number;
  job: string;
  runner: string;
  status: string;
  started_at: number;
  finished_at: number | null;
  error: string | null;
  output: Record<string, unknown> | null;
  transcript: {
    runner?: string;
    steps?: { index: number; tool: string; input_summary: string; ok: boolean | null }[];
    missing_citations?: string[];
    model?: string | null;
    model_requested?: string | null;
    usage?: ConsoleUsage | null;
  };
}

export const JOB_LABEL: Record<string, string> = {
  investigate: "Investigate",
  triage: "Triage",
  respond: "Respond",
  review: "Review",
  author: "Author",
};

/** Each outcome's pill tone: green valid, red rejected or failed, amber for the fake runner. */
export const OUTCOME_TONE: Record<Outcome, "success" | "danger" | "warning" | "neutral" | "agents"> = {
  valid: "success",
  invalid_citation: "danger",
  rerun_rejected: "danger",
  structured_output_failed: "danger",
  failed: "danger",
  fallback: "warning",
  fake: "warning",
  running: "agents",
  unfinished: "neutral",
};

const n = (value: number) => Math.round(value).toLocaleString("en-US");

export function credits(value: number | null | undefined): string {
  return value == null ? "—" : n(value);
}

/** "0.4 s", "45 s", "2 min 05 s". */
export function duration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  const s = ms / 1000;
  if (s < 10) return `${s.toFixed(1)} s`;
  if (s < 120) return `${Math.round(s)} s`;
  const whole = Math.round(s);
  return `${Math.floor(whole / 60)} min ${String(whole % 60).padStart(2, "0")} s`;
}

export function rate(t: Pick<Totals, "valid" | "droid_runs" | "success_rate">): string {
  if (t.success_rate == null) return "no Droid runs yet";
  return `${t.valid} of ${t.droid_runs} (${Math.round(t.success_rate * 100)}%)`;
}

/** A guardrail's count, or why there isn't one. */
export function guardrailCount(g: Guardrail): string {
  return g.count == null ? "not recorded yet" : String(g.count);
}

/** "on 2 of 47 runs" when only some runs record this guardrail. */
export function guardrailCoverage(g: Guardrail, droidRuns: number): string | null {
  if (g.count == null) return "no stored run records it yet";
  if (g.recorded_runs != null && g.recorded_runs < droidRuns) return `recorded on ${g.recorded_runs} of ${droidRuns} Droid runs`;
  return null;
}

/** Built-in tools that still ran in Droid sessions, e.g. "ToolSearch × 2". */
export function builtinCalls(seen: Record<string, number>): string | null {
  const parts = Object.entries(seen).map(([tool, runs]) => `${tool} × ${runs}`);
  return parts.length ? parts.join(", ") : null;
}

/** The model a Droid run used, and what it asked for when Factory switched it. */
export function modelText(run: Pick<ConsoleRun, "runner" | "model" | "model_requested">): string {
  if (run.runner === "fake") return "rules only";
  if (run.runner !== "droid") return "runner not chosen yet"; // 'pending' until the run finishes
  const model = run.model ?? "model not recorded";
  const switched = run.model && run.model_requested && run.model_requested !== "auto" && run.model !== run.model_requested;
  return switched ? `${model} (asked for ${run.model_requested})` : model;
}

/** Which runs the table shows: Droid's own by default, fake-runner ones only when asked. */
export function visibleRuns(runs: ConsoleRun[], withFake: boolean): ConsoleRun[] {
  return withFake ? runs : runs.filter((r) => r.runner === "droid" || r.outcome === "fallback" || r.outcome === "running");
}

/** The reviewer Droid's verdicts on StormDesk's proposals (valid Droid reviews only), or null when there are none. */
export function reviewVerdicts(v: DroidConsole["review_verdicts"]): string | null {
  const parts = [
    v.agree ? `agrees ${v.agree}` : null,
    v.disagree ? `disagrees ${v.disagree}` : null,
    v.insufficient_evidence ? `insufficient evidence ${v.insufficient_evidence}` : null,
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : null;
}

/** "3 turns in 1 Droid session (2 resumed)", or null when no appeal has been answered in a Droid session. */
export function appealSessionsText(a: AppealSessions | undefined): string | null {
  if (!a || a.turns === 0) return null;
  const extra = [`${a.resumed} resumed`, a.restarted ? `${a.restarted} restarted from the stored thread` : null]
    .filter(Boolean).join(", ");
  return `${a.turns} turn${a.turns === 1 ? "" : "s"} in ${a.sessions} Droid session${a.sessions === 1 ? "" : "s"} (${extra})`;
}

/** "turn 2 of Droid session 8c1f2a3b (resumed)" for a respond run that is a turn of its appeal's session. */
export function appealTurnText(a: AppealTurnInfo | null | undefined): string | null {
  if (!a) return null;
  const id = a.session_id ? ` ${a.session_id.replace(/-/g, "").slice(0, 8)}` : "";
  const how = a.session === "resumed" ? "resumed: same session"
    : a.session === "restarted" ? "new session from the stored thread: the last one couldn't be resumed" : "new session";
  return `turn ${a.turn} of Droid session${id} (${how})`;
}

/** What a run's structured output says, for the run view: a summary, a case file, a reply or a review's reasons. */
export function outputText(out: Record<string, unknown> | null): string | null {
  if (!out) return null;
  for (const key of ["summary", "summary_md", "reply", "rationale"]) {
    if (typeof out[key] === "string" && out[key]) return out[key] as string;
  }
  if (Array.isArray(out.reasons) && out.reasons.length) return out.reasons.map((r) => `• ${String(r)}`).join("\n");
  return null;
}

/** "prompt v2", or "reviewer prompt v1" for the second-opinion Droid; null when the run didn't record it. */
export function promptText(run: Pick<ConsoleRun, "job" | "prompt_version">): string | null {
  if (run.prompt_version == null) return null;
  const which = run.job === "review" ? "reviewer prompt" : run.job === "author" ? "author prompt" : "prompt";
  return `${which} v${run.prompt_version}`;
}
