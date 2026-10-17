// Droid tab (spec §18.7): what Factory's Droid does in the running product, from
// the stored StormDesk runs (GET /v1/droid/console). Summary tiles, Droid's runs
// with a click-through to each run's tool calls (replayed step by step), totals
// per job and the guardrail events actually recorded. Fake-runner runs are badged
// and never scored; a guardrail older runs didn't record says so (§0 rule 3).
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { getJSON, type Step } from "../api";
import { replayTitle, RunnerBadge, StepList } from "../components/StormDesk";
import {
  builtinCalls,
  credits,
  duration,
  guardrailCount,
  guardrailCoverage,
  JOB_LABEL,
  modelText,
  OUTCOME_STYLE,
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
import { useEvents } from "../events";
import { clockTime } from "../format";

interface LiveRun {
  run_id: number;
  job: string;
  subject: string;
  runner: string;
  steps: Step[];
}

function startedText(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toDateString() === new Date().toDateString()
    ? clockTime(ts)
    : d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function Tile({ label, value, sub, tone = "text-white" }: { label: string; value: string; sub?: string | null; tone?: string }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
      <div className="text-lg font-medium text-slate-300">{label}</div>
      <div className={`mt-1 font-mono text-4xl font-bold tabular-nums ${tone}`}>{value}</div>
      {sub && <div className="mt-2 text-base text-slate-400">{sub}</div>}
    </div>
  );
}

function OutcomeBadge({ run }: { run: Pick<ConsoleRun, "outcome" | "outcome_label"> }) {
  return (
    <span className={`whitespace-nowrap rounded-full px-3 py-1 text-sm font-semibold ${OUTCOME_STYLE[run.outcome]}`}>
      {run.outcome_label}
    </span>
  );
}

function HarnessStrip({ h, builtin }: { h: Harness; builtin: string | null }) {
  // Who answers the next job (runner.make_runner): auto needs the SDK, the droid CLI and FACTORY_API_KEY.
  const runner = h.runner_setting === "fake" ? "fake runner (STORMDESK_RUNNER=fake)"
    : h.runner_setting === "droid" ? `Droid, model ${h.model_setting}`
    : h.droid_available ? `Droid, model ${h.model_setting} (auto)` : "fake runner (auto: no FACTORY_API_KEY or droid CLI)";
  return (
    <div className="flex flex-wrap items-center gap-2 text-base text-slate-300">
      <span className="rounded-full bg-slate-800 px-3 py-1">New jobs: {runner}</span>
      <span className="rounded-full bg-slate-800 px-3 py-1">
        Prompt v{h.prompt_version}{h.review_prompt_version != null ? ` · reviewer v${h.review_prompt_version}` : ""}
      </span>
      <span className="rounded-full bg-slate-800 px-3 py-1" title={h.read_only_tools.join(", ")}>
        {h.read_only_tools.length} read-only MCP tools · no write tool
      </span>
      <span className="rounded-full bg-slate-800 px-3 py-1">{h.builtin_tools_disabled} built-in tools switched off</span>
      <span className="rounded-full bg-slate-800 px-3 py-1">Worker {h.worker_on ? "on" : "off"}</span>
      {builtin && (
        <span className="rounded-full bg-slate-800 px-3 py-1" title="Droid's ToolSearch still runs once per session to load our MCP tool schemas (spec §14.2).">
          Built-in still seen: {builtin}
        </span>
      )}
      {h.cooldown_s > 0 && (
        <span className="rounded-full bg-amber-500/15 px-3 py-1 font-semibold text-amber-300">
          Droid paused {Math.ceil(h.cooldown_s / 60)} min, fake runner answering: {h.cooldown_reason}
        </span>
      )}
    </div>
  );
}

function LiveNow({ live, onSelect }: { live: LiveRun[]; onSelect: (id: number) => void }) {
  if (live.length === 0) return null;
  return (
    <section className="rounded-2xl border border-sky-500/40 bg-sky-500/5 p-4">
      <h2 className="mb-2 flex items-center gap-2 text-xl font-semibold text-sky-200">
        <span className="h-3 w-3 animate-pulse rounded-full bg-sky-400" /> Running now
      </h2>
      <ul className="space-y-1 text-lg">
        {live.map((r) => {
          const last = r.steps[r.steps.length - 1];
          return (
            <li key={r.run_id}>
              <button onClick={() => onSelect(r.run_id)} className="flex flex-wrap items-center gap-3 text-left hover:underline">
                <span className="font-mono text-slate-400">#{r.run_id}</span>
                <span className="font-semibold text-white">{JOB_LABEL[r.job] ?? r.job}</span>
                <span className="text-slate-300">{r.subject}</span>
                <RunnerBadge runner={r.runner} />
                {last && <span className="font-mono text-sky-300">{r.steps.length} · {last.tool}</span>}
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function RunsTable({ runs, selected, onSelect }: { runs: ConsoleRun[]; selected: number | null; onSelect: (id: number) => void }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-lg">
        <thead className="text-base text-slate-400">
          <tr className="border-b border-slate-800">
            <th className="px-2 py-2 font-medium">Run</th>
            <th className="px-2 py-2 font-medium">Job · subject</th>
            <th className="px-2 py-2 font-medium">Outcome</th>
            <th className="px-2 py-2 text-right font-medium">Credits</th>
            <th className="px-2 py-2 text-right font-medium">Time</th>
            <th className="px-2 py-2 text-right font-medium" title="StormDesk's read-only tool calls">Tools</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.run_id} onClick={() => onSelect(r.run_id)} aria-selected={selected === r.run_id}
              className={`cursor-pointer border-b border-slate-800/60 ${selected === r.run_id ? "bg-slate-800" : "hover:bg-slate-800/50"}`}>
              <td className="whitespace-nowrap px-2 py-2 align-top">
                <div className="font-mono text-slate-200">#{r.run_id}</div>
                <div className="font-mono text-sm text-slate-500">{startedText(r.started_at)}</div>
              </td>
              <td className="px-2 py-2">
                <div className="flex items-baseline gap-2">
                  <span className="font-semibold text-white">{JOB_LABEL[r.job] ?? r.job}</span>
                  <span className="text-sm text-slate-400">{[modelText(r), promptText(r)].filter(Boolean).join(" · ")}</span>
                </div>
                <div className="text-base text-slate-300">{r.subject}</div>
              </td>
              <td className="px-2 py-2"><OutcomeBadge run={r} /></td>
              <td className="whitespace-nowrap px-2 py-2 text-right font-mono tabular-nums text-slate-200">{credits(r.factory_credits)}</td>
              <td className="whitespace-nowrap px-2 py-2 text-right font-mono tabular-nums text-slate-200">{duration(r.duration_ms)}</td>
              <td className="whitespace-nowrap px-2 py-2 text-right font-mono tabular-nums text-slate-200">{r.tool_calls}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="contents">
      <dt className="text-slate-400">{label}</dt>
      <dd className="text-slate-100">{children}</dd>
    </div>
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
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-3xl font-bold text-white">Run #{run.run_id}</h2>
        <span className="rounded-full bg-slate-800 px-3 py-1 text-sm text-slate-200">{JOB_LABEL[run.job] ?? run.job}</span>
        <OutcomeBadge run={run} />
        <RunnerBadge runner={run.runner} model={run.model} modelRequested={run.model_requested} usage={usage} />
      </div>
      <p className="text-lg text-slate-200">{run.subject}{run.verdict ? ` → ${run.verdict}` : ""}</p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-base">
        <Fact label="Model">{modelText(run)}</Fact>
        {run.runner === "droid" && <Fact label="Prompt">{promptText(run) ?? "not recorded"}</Fact>}
        <Fact label="Time">{duration(run.duration_ms)} · started {startedText(run.started_at)}</Fact>
        <Fact label="Factory credits">
          {run.factory_credits != null ? credits(run.factory_credits) : run.runner === "fake" && !run.fallback_reason ? "none (no Droid session)" : "not recorded"}
          {usage?.input_tokens != null && ` · ${(usage.input_tokens + (usage.output_tokens ?? 0)).toLocaleString("en-US")} tokens in + out`}
        </Fact>
        <Fact label="Tool calls">
          {run.tool_calls} read-only{run.tool_errors ? ` (${run.tool_errors} answered with an error)` : ""}{other ? ` + ${other}` : ""}
        </Fact>
        <Fact label="Citations">
          {run.citations_valid ? "every cited id found in the database ✓"
            : run.missing_citations ? `${run.missing_citations} cited id(s) not in the database ✗` : "no output to check"}
        </Fact>
        {run.runner === "droid" && (
          <>
            <Fact label="Output retries">{run.structured_output_retries ?? "not recorded yet"}</Fact>
            <Fact label="Permission denials">{run.permission_denials ?? "not recorded yet"}</Fact>
          </>
        )}
        {run.fallback_reason && <Fact label="Why fake runner"><span className="text-amber-300">Droid couldn't run: {run.fallback_reason}</span></Fact>}
        {run.reviewed_run_id != null && (
          <Fact label="Reviews">
            <button onClick={() => onSelect(run.reviewed_run_id!)} className="text-sky-300 hover:underline">
              StormDesk run #{run.reviewed_run_id}
            </button>
          </Fact>
        )}
        {run.error && !run.fallback_reason && <Fact label="Error"><span className="break-all font-mono text-rose-300">{run.error}</span></Fact>}
      </dl>
      {text && (
        <div className="max-h-56 overflow-y-auto whitespace-pre-wrap rounded-xl border border-slate-800 bg-slate-950 p-4 text-base text-slate-200">
          {text}
        </div>
      )}
      {missing.length > 0 && (
        <div>
          <div className="mb-1 text-base font-semibold text-rose-300">Rejected: cited ids that aren't in the database</div>
          <ul className="flex flex-wrap gap-2 font-mono text-xs">
            {missing.map((id) => (
              <li key={id} className="rounded bg-rose-500/20 px-2 py-1 text-rose-300">{id.length > 20 ? `${id.slice(0, 16)}…` : id}</li>
            ))}
          </ul>
        </div>
      )}
      {live ? (
        <StepList steps={live.steps} live />
      ) : detail?.run_id === run.run_id ? (
        <StepList key={run.run_id} steps={steps} replayLabel={replayTitle(run.started_at, run.runner, run.model)} />
      ) : (
        <p className="rounded-xl border border-slate-800 bg-slate-950 p-4 text-base text-slate-400">
          {failed === run.run_id ? "Couldn't load this run's transcript." : "Loading tool calls…"}
        </p>
      )}
    </div>
  );
}

function JobTable({ rows, verdicts }: { rows: (Totals & { job: string })[]; verdicts: string | null }) {
  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
      <h2 className="mb-3 text-xl font-semibold text-white">Per job</h2>
      {verdicts && (
        <p className="mb-3 text-lg text-slate-200">
          Reviewer Droid on StormDesk's proposals: <span className="font-semibold">{verdicts}</span>
          <span className="text-base text-slate-400"> (valid Droid reviews only)</span>
        </p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-lg">
          <thead className="whitespace-nowrap text-base text-slate-400">
            <tr className="border-b border-slate-800">
              <th className="py-2 pr-3 font-medium">Job</th>
              <th className="px-3 py-2 text-right font-medium">Droid runs</th>
              <th className="px-3 py-2 font-medium">Valid</th>
              <th className="px-3 py-2 text-right font-medium">Mean credits</th>
              <th className="px-3 py-2 text-right font-medium">Mean time</th>
              <th className="px-3 py-2 text-right font-medium" title="Not Droid: never in the success rate">Fake runner</th>
              <th className="py-2 pl-3 text-right font-medium" title="Droid couldn't run; the fake runner answered">Fallbacks</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((j) => (
              <tr key={j.job} className="border-b border-slate-800/60">
                <td className="py-2 pr-3 text-white">{JOB_LABEL[j.job] ?? j.job}</td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">{j.droid_runs}</td>
                <td className="whitespace-nowrap px-3 py-2 text-slate-200">{j.droid_runs ? rate(j) : "—"}</td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">{credits(j.mean_credits)}</td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">{duration(j.mean_duration_ms)}</td>
                <td className="px-3 py-2 text-right font-mono tabular-nums text-amber-300/80">{j.fake_runs}</td>
                <td className="py-2 pl-3 text-right font-mono tabular-nums text-amber-300/80">{j.fallback_runs}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Guardrails({ items, droidRuns, onSelect }: { items: Guardrail[]; droidRuns: number; onSelect: (id: number) => void }) {
  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
      <h2 className="text-xl font-semibold text-white">Guardrails that fired</h2>
      <p className="mb-3 text-base text-slate-400">Counted from stored runs. Click a run to open it.</p>
      <ul className="space-y-3">
        {items.map((g) => {
          const coverage = guardrailCoverage(g, droidRuns);
          return (
            <li key={g.key} className="flex gap-4">
              <div className={`w-14 shrink-0 text-right font-mono text-3xl font-bold tabular-nums ${
                g.count == null ? "text-slate-600" : g.count > 0 ? "text-amber-300" : "text-slate-300"}`}>
                {g.count == null ? "—" : g.count}
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2 text-lg font-semibold text-slate-100">
                  {g.label}
                  {g.count == null && (
                    <span className="rounded-full bg-slate-800 px-2 py-0.5 text-sm font-medium text-slate-300">{guardrailCount(g)}</span>
                  )}
                </div>
                <div className="text-base text-slate-400">{g.about}{coverage ? ` (${coverage})` : ""}</div>
                {g.events.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-2">
                    {g.events.slice(0, 12).map((e) => (
                      <button key={e.run_id} onClick={() => onSelect(e.run_id)} title={e.detail ?? undefined}
                        className="rounded-lg bg-slate-800 px-2 py-1 font-mono text-sm text-slate-200 hover:bg-slate-700">
                        #{e.run_id}{e.runner === "fake" ? " · fake" : ""}
                      </button>
                    ))}
                    {g.events.length > 12 && <span className="text-sm text-slate-400">+{g.events.length - 12} more</span>}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export function DroidTab() {
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

  if (error && !data) return <p className="p-8 text-xl text-rose-300">Couldn't load the Droid console: {error}</p>;
  if (!data) return <p className="p-8 text-xl text-slate-300">Loading…</p>;

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
  };

  return (
    <div className="space-y-6 p-6">
      <div className="space-y-2">
        <h2 className="text-3xl font-bold text-white">Droid in the running product</h2>
        <p className="text-lg text-slate-300">
          Every StormDesk run stored in the database: Factory's Droid SDK with read-only tools, structured outputs and a
          citation check. A person approves anything it proposes. Fake-runner runs are labelled and never scored.
        </p>
        <HarnessStrip h={data.harness} builtin={builtin} />
      </div>

      {data.run_count === 0 ? (
        <section className="rounded-2xl border border-dashed border-slate-700 bg-slate-900/60 p-8">
          <p className="text-2xl text-slate-200">No StormDesk runs yet.</p>
          <p className="mt-2 text-lg text-slate-400">
            They appear here as soon as the worker picks up a hard case or a detector candidate, live as each tool call streams.
          </p>
          <LiveNow live={liveRuns} onSelect={setSelected} />
        </section>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
            <Tile label="Droid runs" value={String(t.droid_runs)}
              sub={`+ ${t.fake_runs} fake runner · ${t.fallback_runs} fallback${t.fallback_runs === 1 ? "" : "s"} (not scored)`} />
            <Tile label="Valid outputs" value={t.success_rate == null ? "—" : `${Math.round(t.success_rate * 100)}%`}
              sub={t.success_rate == null ? "no Droid runs yet" : `${t.valid} of ${t.droid_runs} Droid runs, citations checked`}
              tone={t.success_rate == null ? "text-slate-400" : "text-emerald-300"} />
            <Tile label="Factory credits" value={credits(t.credits_total)}
              sub={t.mean_credits != null ? `mean ${credits(t.mean_credits)} per run (${t.credits_runs} recorded)` : "none recorded"} />
            <Tile label="Mean run time" value={duration(t.mean_duration_ms)} sub={`${t.tool_calls} read-only tool calls in all`} />
            <Tile label="Invalid citations rejected" value={invalid ? guardrailCount(invalid) : "—"}
              sub="stored invalid, never actionable" tone={invalid?.count ? "text-amber-300" : "text-white"} />
          </div>

          <LiveNow live={liveRuns} onSelect={select} />

          <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_34rem]">
            <div className="min-w-0 space-y-6">
              <section className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <h2 className="text-xl font-semibold text-white">{withFake ? "All runs" : "Droid's runs"}</h2>
                  <label className="flex items-center gap-2 text-base text-slate-300">
                    <input type="checkbox" checked={withFake} onChange={(e) => setWithFake(e.target.checked)} className="h-5 w-5" />
                    Show fake-runner runs{!withFake && hidden > 0 ? ` (${hidden} hidden)` : ""}
                  </label>
                </div>
                {runs.length === 0 ? (
                  <p className="text-lg text-slate-400">No Droid runs yet: every stored run so far is the fake runner's.</p>
                ) : (
                  <div className={withFake ? "max-h-[36rem] overflow-y-auto" : undefined}>
                    <RunsTable runs={runs} selected={selected} onSelect={select} />
                  </div>
                )}
                {data.run_count > data.runs.length && (
                  <p className="mt-2 text-sm text-slate-500">Newest {data.runs.length} of {data.run_count} runs; the totals count all of them.</p>
                )}
              </section>
              <Guardrails items={data.guardrails} droidRuns={t.droid_runs} onSelect={select} />
              <JobTable rows={data.by_job} verdicts={reviewVerdicts(data.review_verdicts)} />
            </div>
            <section className="min-w-0 rounded-2xl border border-slate-800 bg-slate-900 p-5 xl:sticky xl:top-4">
              {selectedRun ? (
                <RunView run={selectedRun} live={live.get(selectedRun.run_id)} version={data.as_of} onSelect={select} />
              ) : (
                <p className="text-lg text-slate-400">Pick a run to see its tool calls.</p>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  );
}
