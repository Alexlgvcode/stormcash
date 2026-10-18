// Droid tab (spec §18.7): what Factory's Droid does in the running product, from
// the stored StormDesk runs (GET /v1/droid/console). A summary strip, Droid's
// runs with a click-through to each run's tool calls (replayed step by step), the
// guardrail events actually recorded with totals per job, and the detector
// proposals. Fake-runner runs are badged and never scored; a guardrail older runs
// didn't record says so (§0 rule 3).
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { getJSON, type Step } from "../api";
import { AuthorPanel } from "../components/AuthorDetector";
import { replayTitle, RunnerBadge, StepList } from "../components/StormDesk";
import { Facts, Note, PageHeader, Pill, Section, Strip, Table, Tabs, Td, Th } from "../components/ui";
import {
  appealSessionsText,
  appealTurnText,
  builtinCalls,
  credits,
  duration,
  guardrailCount,
  guardrailCoverage,
  GUARDRAIL_PLAIN,
  JOB_LABEL,
  modelText,
  OUTCOME_PLAIN,
  OUTCOME_TONE,
  outputText,
  promptText,
  rate,
  reviewVerdicts,
  visibleRuns,
  type ConsoleRun,
  type DroidConsole,
  type Guardrail,
  type Harness,
  type RunDetail,
  type Totals,
} from "../droid";
import type { EvalsResponse } from "../evals";
import { useEvents } from "../events";
import { clockTime } from "../format";
import { plainText } from "../plain";

const VIEWS = [
  { id: "runs", label: "Runs" },
  { id: "guardrails", label: "Guardrails" },
  { id: "proposals", label: "Detector proposals" },
] as const;
type View = (typeof VIEWS)[number]["id"];

interface LiveRun {
  run_id: number;
  job: string;
  subject: string;
  runner: string;
  steps: Step[];
}

const startedText = clockTime;

function OutcomeBadge({ run }: { run: Pick<ConsoleRun, "outcome" | "outcome_label"> }) {
  return <Pill tone={OUTCOME_TONE[run.outcome]}>{OUTCOME_PLAIN[run.outcome] ?? run.outcome_label}</Pill>;
}

function HarnessLine({ h, builtin }: { h: Harness; builtin: string | null }) {
  // Who answers the next job (runner.make_runner): auto needs the SDK, the droid CLI and FACTORY_API_KEY.
  const runner = h.runner_setting === "fake" ? "the rules-only stand-in (STORMDESK_RUNNER=fake)"
    : h.runner_setting === "droid" ? `Droid, model ${h.model_setting}`
    : h.droid_available ? `Droid, model ${h.model_setting} (auto)` : "the rules-only stand-in (auto: no FACTORY_API_KEY or droid CLI)";
  const items = [
    `New jobs: ${runner}`,
    `Prompt v${h.prompt_version}${h.review_prompt_version != null ? ` · reviewer v${h.review_prompt_version}` : ""}`,
    `${h.read_only_tools.length} read-only MCP tools, no write tool`,
    `${h.builtin_tools_disabled} built-in tools switched off`,
    `Worker ${h.worker_on ? "on" : "off"}`,
  ];
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-th text-secondary">
      {items.map((t) => (
        <span key={t} title={t.includes("read-only") ? h.read_only_tools.join(", ") : undefined}>{t}</span>
      ))}
      {h.author_on && (
        <span title="The author job (§14.7d): Droid writes two allowlisted files in a sandbox; our code opens a PR a person merges or not.">
          Author job on: sandboxed writes, PR for a person
        </span>
      )}
      {builtin && (
        <span title="Droid's ToolSearch still runs once per session to load our MCP tool schemas (spec §14.2).">
          Built-in still seen: {builtin}
        </span>
      )}
    </div>
  );
}

function LiveNow({ live, onSelect }: { live: LiveRun[]; onSelect: (id: number) => void }) {
  if (live.length === 0) return null;
  return (
    <Section title="Running now">
      <ul>
        {live.map((r) => {
          const last = r.steps[r.steps.length - 1];
          return (
            <li key={r.run_id} className="border-b border-rule py-2.5">
              <button onClick={() => onSelect(r.run_id)} className="flex flex-wrap items-center gap-3 text-left hover:underline">
                <span className="h-2 w-2 animate-pulse rounded-full bg-accent" />
                <span className="tabular-nums text-secondary">#{r.run_id}</span>
                <span className="font-medium text-heading">{JOB_LABEL[r.job] ?? r.job}</span>
                <span className="text-ink">{plainText(r.subject)}</span>
                <RunnerBadge runner={r.runner} />
                {last && <span className="font-mono text-th text-secondary">{r.steps.length} · {last.tool}</span>}
              </button>
            </li>
          );
        })}
      </ul>
    </Section>
  );
}

function RunsTable({ runs, selected, onSelect }: { runs: ConsoleRun[]; selected: number | null; onSelect: (id: number) => void }) {
  return (
    <Table>
      <thead className="sticky top-0 bg-surface">
        <tr>
          <Th className="pl-3">Time</Th>
          <Th className="max-sm:hidden">Job</Th>
          <Th>Subject</Th>
          <Th num className="max-sm:hidden">Credits</Th>
          <Th num className="max-md:hidden">Time</Th>
          <Th>Outcome</Th>
        </tr>
      </thead>
      <tbody>
        {runs.map((r) => {
          const on = selected === r.run_id;
          return (
            <tr key={r.run_id} onClick={() => onSelect(r.run_id)} aria-selected={on}
              className={`cursor-pointer ${on ? "bg-accent-tint" : "hover:bg-surface"}`}>
              <Td className="whitespace-nowrap pl-3">
                <div className="tabular-nums text-secondary">{startedText(r.started_at)}</div>
                <div className="text-th text-secondary">#{r.run_id}</div>
              </Td>
              <Td className={`max-sm:hidden sm:whitespace-nowrap ${on ? "font-semibold text-accent" : "font-medium text-heading"}`}>
                {JOB_LABEL[r.job] ?? r.job}
              </Td>
              <Td className="text-ink">{plainText(r.subject)}</Td>
              <Td num className="max-sm:hidden">{credits(r.factory_credits)}</Td>
              <Td num className="text-secondary max-md:hidden">{duration(r.duration_ms)}</Td>
              <Td className="pr-3"><OutcomeBadge run={r} /></Td>
            </tr>
          );
        })}
      </tbody>
    </Table>
  );
}

function RunView({ run, live, version, onSelect }: {
  run: ConsoleRun;
  live: LiveRun | undefined;
  version: number;
  onSelect: (id: number) => void;
}) {
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [failed, setFailed] = useState<number | null>(null);
  useEffect(() => {
    let current = true;
    getJSON<RunDetail>(`/v1/stormdesk/runs/${run.run_id}`)
      .then((d) => current && setDetail(d))
      .catch(() => current && setFailed(run.run_id));
    return () => {
      current = false;
    };
  }, [run.run_id, version]);

  const text = detail && detail.run_id === run.run_id ? outputText(detail.output) : null;
  const missing = detail?.run_id === run.run_id ? detail.transcript.missing_citations ?? [] : [];
  const steps = detail?.run_id === run.run_id ? detail.transcript.steps ?? [] : [];
  const usage = run.usage;
  const other = builtinCalls(run.other_calls);
  const facts: [string, ReactNode][] = [["Model", modelText(run)]];
  if (run.runner === "droid") facts.push(["Prompt", promptText(run) ?? "not recorded"]);
  facts.push(["Time", `${duration(run.duration_ms)} · started ${startedText(run.started_at)}`]);
  facts.push(["Factory credits", (
    <>
      {run.factory_credits != null ? credits(run.factory_credits)
        : run.runner === "fake" && !run.fallback_reason ? "none (no Droid session)" : "not recorded"}
      {usage?.input_tokens != null && ` · ${(usage.input_tokens + (usage.output_tokens ?? 0)).toLocaleString("en-US")} tokens in + out`}
    </>
  )]);
  facts.push(["Tool calls", `${run.tool_calls} ${run.job === "author" ? "in the sandbox" : "read-only"}${
    run.tool_errors ? ` (${run.tool_errors} answered with an error)` : ""}${other ? ` + ${other.replace(/ToolSearch/g, "loading its tools")}` : ""}`]);
  facts.push([run.job === "author" ? "Re-run" : "Citations", run.job === "author"
    ? (run.outcome === "valid" ? "our server re-ran the tests and the eval: every claim matched ✓"
      : run.outcome === "rerun_rejected" ? "our re-run didn't match Droid's claims: no pull request ✗" : "not checked")
    : run.citations_valid ? "every cited id found in the database ✓"
      : run.missing_citations ? `${run.missing_citations} cited id(s) not in the database ✗` : "no output to check"]);
  if (run.runner === "droid") {
    facts.push(["Output retries", String(run.structured_output_retries ?? "not recorded yet")]);
    facts.push(["Permission denials", String(run.permission_denials ?? "not recorded yet")]);
  }
  if (run.appeal) facts.push(["Appeal", appealTurnText(run.appeal)]);
  if (run.fallback_reason) facts.push(["Why the stand-in answered", <span className="text-warning">Droid couldn't run: {run.fallback_reason}</span>]);
  if (run.reviewed_run_id != null) {
    facts.push(["Reviews", (
      <button onClick={() => onSelect(run.reviewed_run_id!)} className="text-accent hover:underline">
        StormDesk run #{run.reviewed_run_id}
      </button>
    )]);
  }
  if (run.error && !run.fallback_reason) facts.push(["Error", <span className="break-all font-mono text-th text-danger">{run.error}</span>]);

  return (
    <div className="space-y-5">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="mr-1 text-[22px] leading-8 font-semibold text-heading">Run #{run.run_id}</h2>
          <Pill tone="neutral">{JOB_LABEL[run.job] ?? run.job}</Pill>
          <OutcomeBadge run={run} />
          <RunnerBadge runner={run.runner} model={run.model} modelRequested={run.model_requested} usage={usage} />
        </div>
        <p className="mt-2 text-ink">{plainText(run.subject)}{run.verdict ? ` → ${plainText(run.verdict)}` : ""}</p>
      </div>
      <Facts rows={facts} />
      {text && (
        <div className="max-h-56 overflow-y-auto whitespace-pre-wrap border-b border-rule pb-3 text-ink">{text}</div>
      )}
      {missing.length > 0 && (
        <div>
          <div className="mb-1 font-medium text-danger">Rejected: cited ids that aren't in the database</div>
          <ul className="flex flex-wrap gap-2">
            {missing.map((id) => (
              <li key={id}><Pill tone="danger"><span className="font-mono">{id.length > 20 ? `${id.slice(0, 16)}…` : id}</span></Pill></li>
            ))}
          </ul>
        </div>
      )}
      {live ? (
        <StepList steps={live.steps} live />
      ) : detail?.run_id === run.run_id ? (
        <StepList key={run.run_id} steps={steps} replayLabel={replayTitle(run.started_at, run.runner, run.model)} />
      ) : (
        <p className="text-secondary">{failed === run.run_id ? "Couldn't load this run's transcript." : "Loading tool calls…"}</p>
      )}
    </div>
  );
}

function JobTable({ rows, verdicts, appeals }: { rows: (Totals & { job: string })[]; verdicts: string | null; appeals: string | null }) {
  return (
    <Section title="Per job">
      {appeals && (
        <p className="py-2 text-ink">
          Shop appeals by text: <span className="font-medium text-heading">{appeals}</span>
          <span className="text-secondary"> · one Droid session per appeal, resumed for each new message</span>
        </p>
      )}
      {verdicts && (
        <p className="py-2 text-ink">
          Reviewer Droid on StormDesk's proposals: <span className="font-medium text-heading">{verdicts}</span>
          <span className="text-secondary"> (valid Droid reviews only)</span>
        </p>
      )}
      <Table>
        <thead>
          <tr>
            <Th>Job</Th>
            <Th num>Droid runs</Th>
            <Th>Valid</Th>
            <Th num>Mean credits</Th>
            <Th num>Mean time</Th>
            <Th num title="Not Droid: never in the success rate">Stand-in</Th>
            <Th num title="Droid couldn't run; the stand-in answered">Fallbacks</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((j) => (
            <tr key={j.job}>
              <Td className="font-medium text-heading">{JOB_LABEL[j.job] ?? j.job}</Td>
              <Td num>{j.droid_runs}</Td>
              <Td className="whitespace-nowrap">{j.droid_runs ? rate(j) : "—"}</Td>
              <Td num>{credits(j.mean_credits)}</Td>
              <Td num>{duration(j.mean_duration_ms)}</Td>
              <Td num className="text-warning">{j.fake_runs}</Td>
              <Td num className="text-warning">{j.fallback_runs}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Section>
  );
}

function Guardrails({ items, droidRuns, onSelect }: { items: Guardrail[]; droidRuns: number; onSelect: (id: number) => void }) {
  return (
    <Section title="Guardrails that fired">
      <p className="py-2 text-secondary">Counted from stored runs. Click a run to open it.</p>
      <ul className="border-t border-rule">
        {items.map((g) => {
          const coverage = guardrailCoverage(g, droidRuns);
          const plain = GUARDRAIL_PLAIN[g.key] ?? { label: g.label, about: g.about };
          return (
            <li key={g.key} className="grid grid-cols-[minmax(0,1fr)_auto] gap-6 border-b border-rule py-3">
              <div className="min-w-0">
                <div className="font-medium text-heading">{plain.label}</div>
                <div className="text-secondary">{plain.about}{coverage ? ` (${coverage})` : ""}</div>
                {g.events.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
                    {g.events.slice(0, 12).map((e) => (
                      <button key={e.run_id} onClick={() => onSelect(e.run_id)} title={e.detail ?? undefined}
                        className="text-th text-accent hover:underline">
                        #{e.run_id}{e.runner === "fake" ? " · stand-in" : ""}
                      </button>
                    ))}
                    {g.events.length > 12 && <span className="text-th text-secondary">+{g.events.length - 12} more</span>}
                  </div>
                )}
              </div>
              <div className="text-right">
                {g.count == null ? (
                  <Pill tone="neutral">{guardrailCount(g)}</Pill>
                ) : (
                  <span className={`text-section font-semibold tabular-nums ${g.count > 0 ? "text-warning" : "text-heading"}`}>{g.count}</span>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </Section>
  );
}

/** The detector proposals: the author job's runs, and the panel that starts one (it needs the eval gap). */
function Proposals({ runs, onSelect }: { runs: ConsoleRun[]; onSelect: (id: number) => void }) {
  const [evals, setEvals] = useState<EvalsResponse | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    getJSON<EvalsResponse>("/v1/evals").then(setEvals).catch(() => setFailed(true));
  }, []);
  const authored = runs.filter((r) => r.job === "author");
  return (
    <div className="space-y-10">
      <Section title="Author runs">
        {authored.length === 0 ? (
          <p className="py-2.5 text-secondary">No detector proposals yet.</p>
        ) : (
          <RunsTable runs={authored} selected={null} onSelect={onSelect} />
        )}
      </Section>
      {evals ? (
        <AuthorPanel dev={evals.columns.stormdesk} heldout={evals.heldout?.columns.stormdesk ?? null} />
      ) : (
        <Note tone={failed ? "danger" : "neutral"}>{failed ? "Couldn't load the eval results the panel needs." : "Loading…"}</Note>
      )}
    </div>
  );
}

export function DroidTab() {
  const [view, setView] = useState<View>("runs");
  const [data, setData] = useState<DroidConsole | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [withFake, setWithFake] = useState(false);
  const [live, setLive] = useState<Map<number, LiveRun>>(new Map());
  const reloadTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(() => {
    getJSON<DroidConsole>("/v1/droid/console")
      .then((d) => {
        setData(d);
        setError(null);
        setSelected((cur) => cur ?? visibleRuns(d.runs, false)[0]?.run_id ?? d.runs[0]?.run_id ?? null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);
  useEffect(load, [load]);
  useEffect(() => () => {
    if (reloadTimer.current) clearTimeout(reloadTimer.current);
  }, []);
  const reloadSoon = useCallback(() => {
    if (reloadTimer.current) clearTimeout(reloadTimer.current);
    reloadTimer.current = setTimeout(load, 400);
  }, [load]);

  useEvents(["stormdesk_step"], (raw) => {
    const d = raw as Step & { run_id: number; job: string; subject: string; runner: string; done?: boolean };
    setLive((cur) => {
      const next = new Map(cur);
      if (d.done) {
        next.delete(d.run_id);
      } else {
        const run = next.get(d.run_id) ?? { run_id: d.run_id, job: d.job, subject: d.subject, runner: d.runner, steps: [] };
        const steps = [...run.steps.filter((s) => s.index !== d.index),
          { index: d.index, tool: d.tool, input_summary: d.input_summary, ok: d.ok }].sort((a, b) => a.index - b.index);
        next.set(d.run_id, { ...run, runner: d.runner, steps });
      }
      return next;
    });
    if (d.done || !data?.runs.some((r) => r.run_id === d.run_id)) reloadSoon();
  });
  useEvents(["flag"], reloadSoon);

  const t0 = data?.totals;
  const takeaway = t0 && (t0.droid_runs === 0 ? "No Droid runs yet."
    : `Droid ran ${t0.droid_runs} ${t0.droid_runs === 1 ? "time" : "times"} in the product: ${t0.valid} gave valid answers, for ${
      credits(t0.credits_total)} Factory credits in all. A person approves anything it proposes.`);
  const header = (
    <PageHeader title="Droid at work" subtitle="Every Droid run in the product, what it cost, and the guardrails that fired"
      takeaway={takeaway || undefined}>
      <Tabs tabs={VIEWS} value={view} onChange={setView} />
    </PageHeader>
  );
  if (error && !data) return <div className="pb-12">{header}<Note tone="danger">Couldn't load the Droid console: {error}</Note></div>;
  if (!data) return <div className="pb-12">{header}<Note>Loading…</Note></div>;

  const t = data.totals;
  const runs = visibleRuns(data.runs, withFake);
  const hidden = data.runs.length - runs.length;
  const selectedRun = data.runs.find((r) => r.run_id === selected) ?? null;
  const liveRuns = [...live.values()].sort((a, b) => b.run_id - a.run_id);
  const invalid = data.guardrails.find((g) => g.key === "invalid_citation");
  const builtin = builtinCalls(data.builtin_calls_seen);
  const select = (id: number) => {
    if (!runs.some((r) => r.run_id === id)) setWithFake(true); // a fake-runner run: show it in the table too
    setSelected(id);
    setView("runs");
  };

  return (
    <div className="pb-12">
      {header}
      <div className="space-y-3">
        <Strip items={[
          { label: "Droid runs", value: <span className="tabular-nums">{t.droid_runs}</span> },
          { label: "Valid answers", value: t.success_rate == null ? "None yet" : <span className="tabular-nums">{t.valid} of {t.droid_runs}</span> },
          { label: "Factory credits", value: <span className="tabular-nums">{credits(t.credits_total)}</span> },
          { label: "Average time", value: <span className="tabular-nums">{duration(t.mean_duration_ms)}</span> },
        ]} />
        {data.harness.cooldown_s > 0 && (
          <p className="text-warning">
            Droid is paused for {Math.ceil(data.harness.cooldown_s / 60)} min; the rules-only stand-in answers new jobs.
          </p>
        )}
        <details>
          <summary className="cursor-pointer py-1 text-accent">Technical details</summary>
          <div className="mt-2 space-y-2">
            <p className="text-th text-secondary">
              Not scored: {t.fake_runs} rules-only stand-in run{t.fake_runs === 1 ? "" : "s"} and {t.fallback_runs} fallback
              {t.fallback_runs === 1 ? "" : "s"}. Answers rejected for a missing record:{" "}
              {invalid ? guardrailCount(invalid) : "—"}. Write tools: {data.harness.author_on ? "none outside the detector-writing sandbox" : "none"}.
              {t.mean_credits != null ? ` Mean ${credits(t.mean_credits)} credits per run (${t.credits_runs} recorded).` : ""}
            </p>
            <HarnessLine h={data.harness} builtin={builtin} />
            {data.harness.cooldown_s > 0 && data.harness.cooldown_reason && (
              <p className="text-th text-secondary">Why Droid is paused: {data.harness.cooldown_reason}</p>
            )}
          </div>
        </details>
      </div>

      <div className="mt-10">
        {data.run_count === 0 ? (
          <div className="space-y-6">
            <div>
              <p className="text-section text-ink">No StormDesk runs yet.</p>
              <p className="mt-1 text-secondary">
                They appear here as soon as the worker picks up a proven case or a suspicion, live as each tool
                call streams.
              </p>
            </div>
            <LiveNow live={liveRuns} onSelect={select} />
          </div>
        ) : view === "runs" ? (
          <div className="space-y-10">
            <LiveNow live={liveRuns} onSelect={select} />
            <div className="grid items-start gap-10 xl:grid-cols-[minmax(0,1fr)_26rem]">
              <Section
                title={withFake ? "All runs" : "Droid's runs"}
                right={
                  <label className="flex items-center gap-2 text-th text-ink">
                    <input type="checkbox" checked={withFake} onChange={(e) => setWithFake(e.target.checked)}
                      className="h-4 w-4 accent-accent" />
                    Show stand-in runs{!withFake && hidden > 0 ? ` (${hidden} hidden)` : ""}
                  </label>
                }
              >
                {runs.length === 0 ? (
                  <p className="py-2.5 text-secondary">No Droid runs yet: every stored run so far is the stand-in's.</p>
                ) : (
                  <div className={withFake ? "max-h-[36rem] overflow-y-auto" : undefined}>
                    <RunsTable runs={runs} selected={selected} onSelect={select} />
                  </div>
                )}
                {data.run_count > data.runs.length && (
                  <p className="mt-2 text-th text-secondary">
                    Newest {data.runs.length} of {data.run_count} runs; the totals count all of them.
                  </p>
                )}
              </Section>
              <div className="min-w-0 xl:sticky xl:top-6 xl:border-l xl:border-rule xl:pl-10">
                {selectedRun ? (
                  <RunView run={selectedRun} live={live.get(selectedRun.run_id)} version={data.as_of} onSelect={select} />
                ) : (
                  <p className="text-secondary">Pick a run to see its tool calls.</p>
                )}
              </div>
            </div>
          </div>
        ) : view === "guardrails" ? (
          <div className="space-y-10">
            <Guardrails items={data.guardrails} droidRuns={t.droid_runs} onSelect={select} />
            <JobTable rows={data.by_job} verdicts={reviewVerdicts(data.review_verdicts)}
              appeals={appealSessionsText(data.appeal_sessions)} />
          </div>
        ) : (
          <Proposals runs={data.runs} onSelect={select} />
        )}
      </div>
    </div>
  );
}
