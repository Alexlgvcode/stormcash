// "Ask Droid to write a detector" (spec §14.7d, §18.5): an operator points Droid
// at a gap the evals found. Droid writes a deterministic detector in a sandbox;
// our server re-runs its tests and the eval, and only then opens a pull request
// for a person. Nothing here merges, and the live database is never touched.
// The steps stream live (the Cases tab's StepList) and every stored run replays.
import { useCallback, useEffect, useState } from "react";
import { getJSON, operatorPost } from "../api";
import {
  CHECK_LABEL,
  counts,
  gap,
  num,
  PHASE_LABEL,
  ratio,
  verdictLine,
  type AuthorRun,
  type AuthorState,
  type Gap,
} from "../author";
import type { EvalRun } from "../evals";
import { useEvents } from "../events";
import { replayTitle, RunnerBadge, StepList, useLiveSteps } from "./StormDesk";

const KIND = "region_dark"; // the gap the held-out eval found first
const KIND_TITLE: Record<string, string> = {
  region_dark: "Dark regions",
  merchant_silence: "Quiet shops",
  cap_drain: "Drained certificates",
};

function operatorName(): string {
  try {
    return localStorage.getItem("sc-operator") ?? "";
  } catch {
    return "";
  }
}

function MetricsTable({ run }: { run: AuthorRun }) {
  const report = run.transcript?.verified?.eval;
  const name = run.output?.name ?? report?.detector.name;
  if (!report) return null;
  return (
    <table className="mt-2 w-full text-left text-base">
      <thead className="text-slate-400">
        <tr>
          <th className="py-1 pr-3 font-medium">Rows</th>
          <th className="pr-3 font-medium">Detector</th>
          <th className="pr-3 font-medium">Precision</th>
          <th className="pr-3 font-medium">Recall</th>
          <th className="font-medium">TP / FP / FN / TN</th>
        </tr>
      </thead>
      <tbody className="font-mono tabular-nums">
        {(["dev", "heldout"] as const).flatMap((split) => {
          const d = report.data[split];
          const m = report.metrics[split];
          const label = `${split === "dev" ? "Dev" : "Held-out"} · seeds ${d.seeds.join(", ")} · ${d.rows} rows`;
          return [
            <tr key={`${split}-p`} className="border-t border-slate-800">
              <td className="py-1 pr-3 font-sans text-slate-300">{label}</td>
              <td className="pr-3 text-violet-300">{name}</td>
              <td className="pr-3 text-slate-100">{num(m.proposed.precision)}</td>
              <td className="pr-3 text-slate-100">{num(m.proposed.recall)}</td>
              <td className="text-slate-300">{counts(m.proposed)}</td>
            </tr>,
            <tr key={`${split}-r`}>
              <td />
              <td className="pr-3 font-sans text-slate-400">rules only</td>
              <td className="pr-3 text-slate-300">{num(m.rules_only.precision)}</td>
              <td className="pr-3 text-slate-300">{num(m.rules_only.recall)}</td>
              <td className="text-slate-400">{counts(m.rules_only)}</td>
            </tr>,
          ];
        })}
      </tbody>
    </table>
  );
}

function ResultCard({ run }: { run: AuthorRun }) {
  const t = run.transcript;
  const pr = t?.pull_request;
  const ok = run.status === "succeeded";
  const denials = t?.permission_denials ?? [];
  return (
    <div className="space-y-4 rounded-xl border border-slate-800 bg-slate-950 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded-full px-3 py-1 text-sm font-semibold ${
          ok ? "bg-emerald-500/15 text-emerald-300" : "bg-rose-500/15 text-rose-300"}`}>
          {verdictLine(run)}
        </span>
        <RunnerBadge runner={run.runner} model={t?.model} modelRequested={t?.model_requested} usage={t?.usage ?? null} />
        <span className="text-sm text-slate-400">author run #{run.run_id}</span>
      </div>
      {pr?.url && (
        <a href={pr.url} target="_blank" rel="noreferrer" className="block text-xl font-semibold text-sky-300 hover:underline">
          {pr.url.replace("https://github.com/", "")} · labelled “{pr.label}”, waiting for a person
        </a>
      )}
      {pr?.error && <p className="text-rose-300">Pull request failed: {pr.error}</p>}
      {run.output && (
        <div>
          <h4 className="text-lg font-semibold text-slate-100">
            <span className="font-mono text-violet-300">{run.output.name}</span> · judges {run.output.kind} candidates
          </h4>
          <p className="mt-1 text-lg text-slate-200">{run.output.rationale}</p>
        </div>
      )}
      <div>
        <h4 className="text-base font-semibold text-slate-200">Measured by our re-run, after Droid finished</h4>
        <p className="text-sm text-slate-400">
          Labelled simulator candidates (the Chalk eval datasets). Droid saw the dev rows, never a held-out row.
        </p>
        <MetricsTable run={run} />
        {!t?.verified?.eval && <p className="mt-2 text-slate-400">No re-run numbers: the run stopped before the eval.</p>}
      </div>
      {t?.verified && (
        <ul className="space-y-1 text-base">
          {t.verified.checks.map((c) => (
            <li key={c.check} className="flex gap-2">
              <span className={c.ok ? "text-emerald-400" : "text-rose-400"}>{c.ok ? "✓" : "✗"}</span>
              <span className="text-slate-200">{CHECK_LABEL[c.check] ?? c.check}</span>
              {!c.ok && <span className="text-rose-300">{c.detail}</span>}
            </li>
          ))}
        </ul>
      )}
      {run.error && !t?.verified && <p className="text-rose-300">{run.error}</p>}
      {(run.output?.caveats?.length ?? 0) > 0 && (
        <div>
          <h4 className="text-base font-semibold text-slate-200">Droid's caveats</h4>
          <ul className="list-disc pl-6 text-slate-300">
            {run.output!.caveats.map((c) => <li key={c}>{c}</li>)}
          </ul>
        </div>
      )}
      <p className="text-sm text-slate-400">
        Sandbox: worktree of {t?.sandbox?.base_ref ?? "?"} {t?.sandbox?.base_sha?.slice(0, 10)} ·{" "}
        {(t?.lab_runs ?? []).length} lab runs · {denials.length} permission denial{denials.length === 1 ? "" : "s"}
        {t?.stopped_at_credit_cap ? " · stopped at the credit cap" : ""}
      </p>
      {denials.length > 0 && (
        <details className="text-sm text-slate-400">
          <summary className="cursor-pointer">What the sandbox refused</summary>
          <ul className="mt-1 space-y-1 font-mono">
            {denials.map((d, i) => <li key={i}>{d.tool} {d.target ?? ""}: {d.reason}</li>)}
          </ul>
        </details>
      )}
      {t?.verified?.files && Object.keys(t.verified.files).length > 0 && (
        <details>
          <summary className="cursor-pointer text-base text-slate-300">The code Droid wrote</summary>
          {Object.entries(t.verified.files).map(([path, text]) => (
            <div key={path} className="mt-2">
              <div className="font-mono text-sm text-slate-400">{path}</div>
              <pre className="mt-1 max-h-80 overflow-auto rounded-lg bg-slate-900 p-3 text-sm text-slate-200">{text}</pre>
            </div>
          ))}
        </details>
      )}
      {t?.steps && (
        <StepList steps={t.steps} replayLabel={replayTitle(run.started_at, run.runner, t.model)} />
      )}
    </div>
  );
}

export function AuthorPanel({ dev, heldout }: { dev: EvalRun | null; heldout: EvalRun | null }) {
  const [state, setState] = useState<AuthorState | null>(null);
  const [runId, setRunId] = useState<number | null>(null);
  const [run, setRun] = useState<AuthorRun | null>(null);
  const [phase, setPhase] = useState<string | null>(null);
  const [operator, setOperator] = useState(operatorName);
  const [error, setError] = useState<string | null>(null);
  const live = useLiveSteps(runId ? `author run #${runId}` : "");
  const g: Gap = gap(KIND, dev, heldout);

  const loadRun = useCallback((id: number) => {
    getJSON<AuthorRun>(`/v1/stormdesk/runs/${id}`).then(setRun).catch((e: Error) => setError(e.message));
  }, []);

  const loadState = useCallback(() => {
    getJSON<AuthorState>("/v1/stormdesk/author-detector")
      .then((s) => {
        setState(s);
        const latest = s.runs[0]?.run_id;
        setRunId((cur) => cur ?? latest ?? null);
        if (latest && !s.running) loadRun(latest);
      })
      .catch((e: Error) => setError(e.message));
  }, [loadRun]);

  useEffect(loadState, [loadState]);

  useEvents(["author"], (raw) => {
    const d = raw as { run_id: number; phase: string };
    if (d.run_id !== runId) return;
    setPhase(d.phase);
    if (d.phase === "done") {
      loadRun(d.run_id);
      loadState();
    }
  });

  const running = phase !== null && phase !== "done";
  useEffect(() => {
    if (!running || runId === null) return;
    const timer = setInterval(() => {  // in case an SSE event was missed
      getJSON<AuthorRun>(`/v1/stormdesk/runs/${runId}`).then((r) => {
        if (r.status !== "running") {
          setRun(r);
          setPhase("done");
          loadState();
        }
      }).catch(() => undefined);
    }, 5000);
    return () => clearInterval(timer);
  }, [running, runId, loadState]);

  async function start() {
    if (!operator.trim()) {
      setError("Type your name first: an operator starts every author run.");
      return;
    }
    try {
      localStorage.setItem("sc-operator", operator.trim());
    } catch {
      // private window: the name isn't remembered
    }
    setError(null);
    try {
      const r = await operatorPost<{ run_id: number }>("/v1/stormdesk/author-detector",
        { gap: `${KIND}: StormDesk caught ${ratio(g.heldout)} dark regions on held-out towns`, examples: g.examples },
        operator.trim());
      live.reset();
      setRun(null);
      setRunId(r.run_id);
      setPhase("sandbox");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <section className="space-y-4 rounded-2xl border border-violet-700/60 bg-slate-900 p-5">
      <div>
        <h3 className="text-2xl font-semibold text-violet-200">Ask Droid to write a detector</h3>
        <p className="mt-1 text-lg text-slate-300">
          Droid writes a deterministic detector in a throwaway sandbox and proves it on labelled data. Our server
          re-runs its tests and the eval, then opens a pull request for a person. It never merges and never touches
          the live database.
        </p>
      </div>
      <div className="rounded-xl bg-slate-950 p-4 text-lg">
        <span className="font-semibold text-slate-100">{KIND_TITLE[KIND]}:</span>{" "}
        <span className="text-slate-300">
          StormDesk caught {ratio(g.dev)} on dev rows and {ratio(g.heldout)} on held-out rows. The rules-only
          baseline flags every quiet region too.
        </span>
        {g.examples.length > 0 && (
          <div className="mt-2 text-base text-slate-400">
            Dev rows Droid is shown as examples:{" "}
            {g.examples.map((id) => <span key={id} className="mr-2 rounded bg-slate-800 px-2 py-0.5 font-mono">{id}</span>)}
          </div>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <input value={operator} onChange={(e) => setOperator(e.target.value)} placeholder="Your name"
          className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-lg text-slate-100" />
        <button onClick={start} disabled={!state?.enabled || running || state?.running}
          className="rounded-lg bg-violet-600 px-5 py-2 text-lg font-semibold text-white hover:bg-violet-500 disabled:opacity-40">
          {running || state?.running ? "Droid is working…" : "Ask Droid to write a detector"}
        </button>
        {state && (
          <span className="text-sm text-slate-400">
            {state.model} · stops at {state.max_credits.toLocaleString("en-US")} credits · {state.budget.test} test and{" "}
            {state.budget.eval} eval runs
          </span>
        )}
      </div>
      {state && !state.enabled && (
        <p className="text-base text-amber-300">Off on this server: {state.reasons.join("; ")}.</p>
      )}
      {error && <p className="text-rose-300">{error}</p>}
      {running && (
        <div className="space-y-2">
          <p className="text-lg text-sky-300">{PHASE_LABEL[phase!] ?? phase}…</p>
          <StepList steps={live.steps} live />
        </div>
      )}
      {run && run.status !== "running" && <ResultCard run={run} />}
    </section>
  );
}
