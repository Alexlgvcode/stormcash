// Evals tab (spec §18.5, §15.3): the saved Chalk runs of the StormDesk triage
// eval, rules-only baseline next to StormDesk. Only a real Droid run fills the
// StormDesk column (the server checks); fake-runner runs are listed as pipeline
// checks without their numbers, and nothing is ever a placeholder (§0 rule 3).
import { useCallback, useEffect, useState } from "react";
import { getJSON } from "../api";
import {
  METRICS,
  SCENARIO_LABEL,
  scenarioCell,
  trapsRight,
  type Cell,
  type EvalRow,
  type EvalRun,
  type EvalSection,
  type EvalsResponse,
} from "../evals";
import { dollars } from "../format";

const REFRESH_MS = 60_000; // results files are read on every request, so a new run shows up on its own

function when(ts: number): string {
  return new Date(ts * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function cellText(cell: Cell): string {
  if (typeof cell === "string") return cell;
  return cell.of === undefined ? dollars(cell.cents) : `${dollars(cell.cents)} of ${dollars(cell.of)}`;
}

const MODE_LABEL: Record<string, string> = {
  chalk_task: "Chalk task",
  run_local: "run locally, scored in Chalk",
};

function RunCard({ title, run, empty }: { title: string; run: EvalRun | null; empty: string }) {
  if (!run) {
    return (
      <section className="rounded-2xl border border-dashed border-slate-700 bg-slate-900/60 p-5">
        <h3 className="text-xl font-semibold text-slate-200">{title}</h3>
        <p className="mt-3 text-2xl text-slate-300">{empty}</p>
        <p className="mt-2 text-slate-400">It fills in when a Droid run's results file is saved in chalk/evals/results.</p>
      </section>
    );
  }
  const d = run.dataset;
  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-xl font-semibold text-slate-200">{title}</h3>
        <span className="text-slate-400">{when(run.timestamp)}</span>
      </div>
      {(run.runner_label !== title || run.model) && (
        <p className="mt-1 text-lg text-slate-300">{[run.runner_label !== title && run.runner_label, run.model].filter(Boolean).join(" · ")}</p>
      )}
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-base">
        <dt className="text-slate-400">Chalk run</dt>
        <dd className="break-all font-mono text-slate-100">
          {run.chalk.dashboard_url ? (
            <a href={run.chalk.dashboard_url} target="_blank" rel="noreferrer" className="text-sky-300 hover:underline">
              {run.chalk.run_id}
            </a>
          ) : (
            run.chalk.run_id
          )}
        </dd>
        <dt className="text-slate-400">In Chalk</dt>
        <dd className="text-slate-200">
          Evaluations → {run.chalk.suite} → {run.chalk.evaluation_name} ({run.chalk.status.toLowerCase()})
        </dd>
        <dt className="text-slate-400">Dataset</dt>
        <dd className="text-slate-200">
          {d.rows} candidates ({d.honest_rows} honest) from seeds {d.seeds.join(", ")}
        </dd>
        <dt className="text-slate-400">How</dt>
        <dd className="text-slate-200">{MODE_LABEL[run.mode] ?? run.mode}</dd>
      </dl>
    </section>
  );
}

function NoStormDesk({ rows }: { rows: number }) {
  return (
    <td rowSpan={rows} className="border-l border-slate-800 px-4 text-center align-middle text-xl text-slate-400">
      No StormDesk run yet
    </td>
  );
}

function Comparison({ rules, desk }: { rules: EvalRun | null; desk: EvalRun | null }) {
  return (
    <section className="overflow-x-auto rounded-2xl border border-slate-800 bg-slate-900 p-5">
      <h3 className="mb-3 text-xl font-semibold text-slate-200">Rules-only vs. StormDesk</h3>
      <table className="w-full min-w-[40rem] text-left text-lg">
        <thead className="text-slate-400">
          <tr>
            <th className="py-2 pr-4 font-medium">Metric</th>
            <th className="px-4 font-medium">Rules-only baseline</th>
            <th className="border-l border-slate-800 px-4 font-medium">StormDesk (Droid)</th>
          </tr>
        </thead>
        <tbody>
          {METRICS.map((m, i) => (
            <tr key={m.label} className="border-t border-slate-800">
              <td className="py-2 pr-4">
                <div className="text-slate-100">{m.label}</div>
                <div className="text-sm text-slate-500">{m.hint}</div>
              </td>
              <td className="px-4 font-mono tabular-nums text-slate-100">{rules ? cellText(m.cell(rules)) : "No run yet"}</td>
              {desk ? (
                <td className="border-l border-slate-800 px-4 font-mono tabular-nums text-slate-100">
                  {cellText(m.cell(desk))}
                </td>
              ) : (
                i === 0 && <NoStormDesk rows={METRICS.length} />
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function Scenarios({ rules, desk }: { rules: EvalRun | null; desk: EvalRun | null }) {
  const names = [...new Set([...(rules?.per_scenario ?? []), ...(desk?.per_scenario ?? [])].map((s) => s.scenario))];
  return (
    <section className="overflow-x-auto rounded-2xl border border-slate-800 bg-slate-900 p-5">
      <h3 className="mb-3 text-xl font-semibold text-slate-200">By scenario</h3>
      <table className="w-full min-w-[40rem] text-left text-lg">
        <thead className="text-slate-400">
          <tr>
            <th className="py-2 pr-4 font-medium">Scenario</th>
            <th className="px-4 font-medium">Candidates</th>
            <th className="px-4 font-medium">Right answer</th>
            <th className="px-4 font-medium">Rules-only</th>
            <th className="border-l border-slate-800 px-4 font-medium">StormDesk</th>
          </tr>
        </thead>
        <tbody>
          {names.map((name, i) => {
            const r = rules?.per_scenario.find((s) => s.scenario === name);
            const s = desk?.per_scenario.find((x) => x.scenario === name);
            const info = (r ?? s)!;
            return (
              <tr key={name} className="border-t border-slate-800">
                <td className="py-2 pr-4 text-slate-100">{SCENARIO_LABEL[name] ?? name}</td>
                <td className="px-4 font-mono tabular-nums">{info.rows}</td>
                <td className="px-4 text-slate-300">{info.honest ? "leave alone" : info.label_action}</td>
                <td className={`whitespace-nowrap px-4 font-mono ${info.honest && r?.dismissed === 0 ? "text-rose-300" : "text-slate-100"}`}>
                  {scenarioCell(r) ?? "No run yet"}
                </td>
                {desk ? (
                  <td className={`whitespace-nowrap border-l border-slate-800 px-4 font-mono ${
                    info.honest && s?.dismissed === 0 ? "text-rose-300" : "text-slate-100"}`}>
                    {scenarioCell(s) ?? "n/a"}
                  </td>
                ) : (
                  i === 0 && <NoStormDesk rows={names.length} />
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

function TrapRow({ row, open }: { row: EvalRow; open: boolean }) {
  return (
    <details open={open} className="rounded-xl border border-slate-800 bg-slate-950 p-4">
      <summary className="cursor-pointer text-lg text-slate-100">
        {row.subject_name ?? row.subject_id} · {SCENARIO_LABEL[row.label_scenario] ?? row.label_scenario} · seed{" "}
        {row.seed} · left alone ({row.output_kind ?? "no flag"}, {row.output_action ?? "no action"})
      </summary>
      {row.summary && <p className="mt-3 text-lg text-slate-200">{row.summary}</p>}
      {row.reasoning && <pre className="mt-2 whitespace-pre-wrap font-sans text-base text-slate-300">{row.reasoning}</pre>}
      {row.evidence_ids.length > 0 && (
        <p className="mt-2 break-all font-mono text-sm text-slate-400">Evidence: {row.evidence_ids.join(", ")}</p>
      )}
    </details>
  );
}

function Traps({ rules, desk }: { rules: EvalRun | null; desk: EvalRun | null }) {
  const right = desk ? trapsRight(desk) : [];
  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
      <h3 className="mb-3 text-xl font-semibold text-slate-200">Trap cases StormDesk got right</h3>
      {!desk && (
        <p className="text-lg text-slate-400">
          Appears with the first StormDesk run.
          {rules &&
            ` The rules-only baseline left ${trapsRight(rules).length} of ${rules.dataset.honest_rows} traps alone: it flags every candidate.`}
        </p>
      )}
      {desk && right.length === 0 && (
        <p className="text-lg text-slate-400">None: it flagged every honest subject in the dataset.</p>
      )}
      {desk && right.length > 0 && (
        <div className="space-y-3">
          <p className="text-slate-400">
            {right.length} of {desk.dataset.honest_rows} traps left alone.
          </p>
          {right.map((row, i) => (
            <TrapRow key={row.row_id} row={row} open={i === 0} />
          ))}
        </div>
      )}
    </section>
  );
}

function HeldOut({ section }: { section: EvalSection }) {
  const { rules_only: rules, stormdesk: desk } = section.columns;
  const shown = desk ?? rules;
  if (!shown) return null;
  return (
    <section className="space-y-4 rounded-2xl border border-amber-700/60 bg-slate-900/40 p-5">
      <div>
        <h3 className="text-2xl font-semibold text-amber-200">Held-out seeds {shown.dataset.seeds.join(", ")}</h3>
        <p className="mt-1 text-lg text-slate-300">
          Chosen before the run and never seen while the prompt was written. {shown.dataset.rows} rows, scored apart
          from the comparison above.
        </p>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <RunCard title="Rules-only baseline" run={rules} empty="No rules-only run on these rows yet." />
        <RunCard title="StormDesk (Droid)" run={desk} empty="No StormDesk run on the held-out seeds yet." />
      </div>
      <Comparison rules={rules} desk={desk} />
      <Scenarios rules={rules} desk={desk} />
    </section>
  );
}

export function EvalsTab() {
  const [data, setData] = useState<EvalsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    getJSON<EvalsResponse>("/v1/evals")
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  if (error && !data) return <p className="p-8 text-xl text-rose-300">Couldn't load the eval results: {error}</p>;
  if (!data) return <p className="p-8 text-xl text-slate-400">Loading eval results…</p>;

  const { rules_only: rules, stormdesk: desk } = data.columns;
  const shown = rules ?? desk;
  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-2xl font-semibold">StormDesk triage eval · Chalk</h2>
        <button onClick={load} className="rounded-lg border border-slate-700 px-4 py-2 text-slate-300 hover:bg-slate-800">
          Reload results
        </button>
      </div>

      {!shown && <p className="text-3xl text-slate-300">No eval run yet.</p>}

      {shown && (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            <RunCard title="Rules-only baseline" run={rules} empty="No rules-only run yet." />
            <RunCard title="StormDesk (Droid)" run={desk} empty="No StormDesk run yet." />
          </div>
          <Comparison rules={rules} desk={desk} />
          <Scenarios rules={rules} desk={desk} />
          <Traps rules={rules} desk={desk} />
          {shown.dataset.detector_misses.length > 0 && (
            <section className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
              <h3 className="text-xl font-semibold text-slate-200">Not in the dataset</h3>
              <p className="mt-1 text-slate-400">
                {shown.dataset.detector_misses.length} planted subjects never raised a candidate, so neither runner saw
                them (they aren't counted above):
              </p>
              <ul className="mt-2 space-y-1 text-lg text-slate-300">
                {shown.dataset.detector_misses.map((m) => (
                  <li key={`${m.seed}:${m.subject_id}`}>
                    {m.name} · {SCENARIO_LABEL[m.scenario] ?? m.scenario} · seed {m.seed}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}

      {data.heldout && <HeldOut section={data.heldout} />}

      {[...data.other_runs, ...(data.heldout?.other_runs ?? [])].length > 0 && (
        <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
          <h3 className="text-xl font-semibold text-slate-200">Other saved runs (not shown as scores)</h3>
          <ul className="mt-2 space-y-2 text-base text-slate-300">
            {[...data.other_runs, ...(data.heldout?.other_runs ?? [])].map((r) => (
              <li key={r.file}>
                {r.timestamp ? when(r.timestamp) : r.file} · {r.reason}
                {r.mode ? ` (${MODE_LABEL[r.mode] ?? r.mode})` : ""} ·{" "}
                <span className="break-all font-mono text-slate-400">Chalk run {r.chalk_run_id ?? "?"}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {data.errors.length > 0 && (
        <p className="text-rose-300">
          Couldn't read: {data.errors.map((e) => `${e.file} (${e.error})`).join("; ")}
        </p>
      )}
    </div>
  );
}
