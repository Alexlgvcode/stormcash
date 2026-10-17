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
import { Button, Pill, Section, Table, Td, TextInput, Th } from "./ui";

const KIND = "region_dark"; // the gap the held-out eval found first
const KIND_TITLE: Record<string, string> = {
  region_dark: "Dark areas",
  merchant_silence: "Quiet shops",
  cap_drain: "Fast-drained wallets",
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
    <Table>
      <thead>
        <tr>
          <Th>Rows</Th>
          <Th>Detector</Th>
          <Th num>Precision</Th>
          <Th num>Recall</Th>
          <Th num>TP / FP / FN / TN</Th>
        </tr>
      </thead>
      <tbody>
        {(["dev", "heldout"] as const).flatMap((split) => {
          const d = report.data[split];
          const m = report.metrics[split];
          const label = `${split === "dev" ? "Dev" : "Held-out"} · seeds ${d.seeds.join(", ")} · ${d.rows} rows`;
          return [
            <tr key={`${split}-p`}>
              <Td rule={false} className="text-ink">{label}</Td>
              <Td rule={false} className="font-mono text-th font-medium text-heading">{name}</Td>
              <Td rule={false} num className="font-medium text-heading">{num(m.proposed.precision)}</Td>
              <Td rule={false} num className="font-medium text-heading">{num(m.proposed.recall)}</Td>
              <Td rule={false} num>{counts(m.proposed)}</Td>
            </tr>,
            <tr key={`${split}-r`} className="text-secondary">
              <Td />
              <Td>rules only</Td>
              <Td num>{num(m.rules_only.precision)}</Td>
              <Td num>{num(m.rules_only.recall)}</Td>
              <Td num>{counts(m.rules_only)}</Td>
            </tr>,
          ];
        })}
      </tbody>
    </Table>
  );
}

function ResultCard({ run }: { run: AuthorRun }) {
  const t = run.transcript;
  const pr = t?.pull_request;
  const ok = run.status === "succeeded";
  const denials = t?.permission_denials ?? [];
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <Pill tone={ok ? "success" : "danger"}>{verdictLine(run)}</Pill>
        <RunnerBadge runner={run.runner} model={t?.model} modelRequested={t?.model_requested} usage={t?.usage ?? null} />
        <span className="text-th text-secondary">author run #{run.run_id}</span>
      </div>
      {pr?.url && (
        <a href={pr.url} target="_blank" rel="noreferrer" className="block text-section font-medium text-accent hover:underline">
          {pr.url.replace("https://github.com/", "")} · labelled “{pr.label}”, waiting for a person
        </a>
      )}
      {pr?.error && <p className="text-danger">Pull request failed: {pr.error}</p>}
      {run.output && (
        <div>
          <p className="font-medium text-heading">
            <span className="font-mono">{run.output.name}</span> · judges {(KIND_TITLE[run.output.kind] ?? run.output.kind).toLowerCase()}
          </p>
          <p className="mt-1 max-w-[90ch] text-ink">{run.output.rationale}</p>
        </div>
      )}
      <div>
        <p className="font-medium text-heading">Measured by our re-run, after Droid finished</p>
        <p className="mb-2 text-th text-secondary">
          Labelled cases from the simulated towns (the Chalk eval datasets). Droid saw the dev rows, never a held-out row.
        </p>
        <MetricsTable run={run} />
        {!t?.verified?.eval && <p className="mt-2 text-secondary">No re-run numbers: the run stopped before the eval.</p>}
      </div>
      {t?.verified && (
        <ul className="border-t border-rule">
          {t.verified.checks.map((c) => (
            <li key={c.check} className="flex gap-3 border-b border-rule py-2">
              <span className={c.ok ? "text-success" : "text-danger"}>{c.ok ? "✓" : "✗"}</span>
              <span className="text-ink">{CHECK_LABEL[c.check] ?? c.check}</span>
              {!c.ok && <span className="text-danger">{c.detail}</span>}
            </li>
          ))}
        </ul>
      )}
      {run.error && !t?.verified && <p className="text-danger">{run.error}</p>}
      {(run.output?.caveats?.length ?? 0) > 0 && (
        <div>
          <p className="font-medium text-heading">Droid's caveats</p>
          <ul className="mt-1 list-disc pl-6 text-ink">
            {run.output!.caveats.map((c) => <li key={c}>{c}</li>)}
          </ul>
        </div>
      )}
      <p className="text-th text-secondary">
        Sandbox: worktree of {t?.sandbox?.base_ref ?? "?"} {t?.sandbox?.base_sha?.slice(0, 10)} ·{" "}
        {(t?.lab_runs ?? []).length} lab runs · {denials.length} permission denial{denials.length === 1 ? "" : "s"}
        {t?.stopped_at_credit_cap ? " · stopped at the credit cap" : ""}
      </p>
      {denials.length > 0 && (
        <details className="text-th text-secondary">
          <summary className="cursor-pointer text-accent">What the sandbox refused</summary>
          <ul className="mt-1 space-y-1 font-mono">
            {denials.map((d, i) => <li key={i}>{d.tool} {d.target ?? ""}: {d.reason}</li>)}
          </ul>
        </details>
      )}
      {t?.verified?.files && Object.keys(t.verified.files).length > 0 && (
        <details>
          <summary className="cursor-pointer text-accent">The code Droid wrote</summary>
          {Object.entries(t.verified.files).map(([path, text]) => (
            <div key={path} className="mt-2">
              <div className="font-mono text-th text-secondary">{path}</div>
              <pre className="mt-1 max-h-80 overflow-auto border-y border-rule py-2 text-th text-ink">{text}</pre>
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
    <Section title="Ask Droid to write a detector">
      <div className="space-y-5 pt-2">
        <p className="max-w-[90ch] text-ink">
          Droid writes a deterministic detector in a throwaway sandbox and proves it on labelled data. Our server
          re-runs its tests and the eval, then opens a pull request for a person. It never merges and never touches
          the live database.
        </p>
        <div>
          <p className="text-ink">
            <span className="font-medium text-heading">{KIND_TITLE[KIND]}:</span> StormDesk caught {ratio(g.dev)} on dev
            rows and {ratio(g.heldout)} on held-out rows. The rules-only baseline flags every quiet area too.
          </p>
          {g.examples.length > 0 && (
            <p className="mt-1 text-th text-secondary">
              Dev rows Droid is shown as examples:{" "}
              {g.examples.map((id) => <span key={id} className="mr-2 font-mono">{id}</span>)}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <TextInput value={operator} onChange={(e) => setOperator(e.target.value)} placeholder="Your name" />
          <Button primary onClick={start} disabled={!state?.enabled || running || state?.running}>
            {running || state?.running ? "Droid is working…" : "Ask Droid to write a detector"}
          </Button>
          {state && (
            <span className="text-th text-secondary">
              {state.model} · stops at {state.max_credits.toLocaleString("en-US")} credits · {state.budget.test} test and{" "}
              {state.budget.eval} eval runs
            </span>
          )}
        </div>
        {state && !state.enabled && (
          <p className="text-warning" title={state.reasons.join("; ")}>
            Writing detectors is switched off on this server, so this button does nothing here.{run ? " The last run is below." : ""}
          </p>
        )}
        {error && <p className="text-danger">{error}</p>}
        {running && (
          <div className="space-y-2">
            <p className="text-accent">{PHASE_LABEL[phase!] ?? phase}…</p>
            <StepList steps={live.steps} live />
          </div>
        )}
        {run && run.status !== "running" && <ResultCard run={run} />}
      </div>
    </Section>
  );
}
