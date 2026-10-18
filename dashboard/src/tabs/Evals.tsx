// Evals tab (spec §18.5, §15.3): the saved Chalk runs of the StormDesk triage
// eval, rules-only baseline next to StormDesk, held-out towns first. Only a
// real Droid run fills the StormDesk column (the server checks); fake-runner and
// incomplete runs are listed as pipeline checks without their numbers, and
// nothing is ever a placeholder (§0 rule 3).
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { getJSON } from "../api";
import { ACTION_PLAIN, KIND_PLAIN } from "../plain";
import { AuthorPanel } from "../components/AuthorDetector";
import { Button, Facts, Note, PageHeader, Section, Strip, Table, Tabs, Td, Th } from "../components/ui";
import {
  evalsTakeaway,
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
import { clockTime, dollars } from "../format";

const REFRESH_MS = 60_000; // results files are read on every request, so a new run shows up on its own

const VIEWS = [
  { id: "heldout", label: "Held-out towns" },
  { id: "main", label: "Main dataset" },
  { id: "runs", label: "Runs" },
] as const;
type View = (typeof VIEWS)[number]["id"];

const when = clockTime;

// Server-written run labels in plain words: the deterministic baseline runner is a stand-in, not an agent.
const plainLabel = (text: string) => text.replace(/Fake runner/g, "Rules-only stand-in").replace(/ · prompt v\d+/g, "");

function cellText(cell: Cell): string {
  if (typeof cell === "string") return cell;
  return cell.of === undefined ? dollars(cell.cents) : `${dollars(cell.cents)} of ${dollars(cell.of)}`;
}

const MODE_LABEL: Record<string, string> = {
  chalk_task: "Chalk task",
  run_local: "run locally, scored in Chalk",
};

/** A Chalk run id, shortened; a click copies the whole id. Linked when the results file carries its URL. */
function ChalkId({ id, url }: { id: string; url?: string | null }) {
  const [copied, setCopied] = useState(false);
  function copy() {
    navigator.clipboard?.writeText(id).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }).catch(() => undefined);
  }
  return (
    <span className="inline-flex items-baseline gap-2">
      <button onClick={copy} title={`${id} (click to copy)`} className="font-mono text-th text-ink hover:text-accent">
        {id.slice(0, 8)}…
      </button>
      {copied && <span className="text-th text-success">copied</span>}
      {url && (
        <a href={url} target="_blank" rel="noreferrer" className="text-th text-accent hover:underline">open in Chalk</a>
      )}
    </span>
  );
}

function ChalkRun({ run }: { run: EvalRun }) {
  return <ChalkId id={run.chalk.run_id} url={run.chalk.dashboard_url} />;
}

/** One section's headline facts, from its StormDesk run (else the baseline). */
function SectionStrip({ rules, desk, heldout }: { rules: EvalRun | null; desk: EvalRun | null; heldout: boolean }) {
  const shown = desk ?? rules;
  if (!shown) return null;
  const d = shown.dataset;
  return (
    <Strip items={[
      { label: "Towns", value: `Seeds ${d.seeds.join(", ")}${heldout ? ", chosen before the run" : ""}` },
      { label: "Cases", value: <span className="tabular-nums">{d.rows} ({d.honest_rows} honest)</span> },
      { label: "StormDesk model", value: desk ? (desk.model ?? "not recorded") : "No StormDesk run yet" },
      { label: "Chalk run", value: <ChalkRun run={shown} /> },
    ]} />
  );
}

function RunFacts({ title, run, empty }: { title: string; run: EvalRun | null; empty: string }) {
  return (
    <Section title={title}>
      {!run ? (
        <div className="py-2.5">
          <p className="text-ink">{empty}</p>
          <p className="mt-1 text-secondary">It fills in when a Droid run's results file is saved in chalk/evals/results.</p>
        </div>
      ) : (
        <Facts rows={[
          ["When", when(run.timestamp)],
          ["Runner", plainLabel([run.runner_label, run.model].filter(Boolean).join(" · "))],
          ["Chalk run", <ChalkRun run={run} />],
          ["In Chalk", `Evaluations → ${run.chalk.suite} → ${run.chalk.evaluation_name} (${run.chalk.status.toLowerCase()})`],
          ["Dataset", `${run.dataset.rows} cases (${run.dataset.honest_rows} honest) from seeds ${run.dataset.seeds.join(", ")}`],
          ["How", MODE_LABEL[run.mode] ?? run.mode],
        ]} />
      )}
    </Section>
  );
}

function NoStormDesk({ rows }: { rows: number }) {
  return (
    <td rowSpan={rows} className="border-b border-l border-rule px-6 text-center align-middle text-secondary">
      No StormDesk run yet
    </td>
  );
}

function Comparison({ rules, desk }: { rules: EvalRun | null; desk: EvalRun | null }) {
  return (
    <Table>
      <thead>
        <tr>
          <Th>Metric</Th>
          <Th num>Rules-only baseline</Th>
          <Th num className="pl-6">StormDesk (Droid)</Th>
        </tr>
      </thead>
      <tbody>
        {METRICS.map((m, i) => (
          <tr key={m.label}>
            <Td>
              <div className="text-heading">{m.label}</div>
              <div className="text-th text-secondary">{m.hint}</div>
            </Td>
            <Td num>{rules ? cellText(m.cell(rules)) : <span className="text-secondary">No run yet</span>}</Td>
            {desk ? (
              <Td num className="pl-6 font-medium text-heading">{cellText(m.cell(desk))}</Td>
            ) : (
              i === 0 && <NoStormDesk rows={METRICS.length} />
            )}
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function Scenarios({ rules, desk }: { rules: EvalRun | null; desk: EvalRun | null }) {
  const names = [...new Set([...(rules?.per_scenario ?? []), ...(desk?.per_scenario ?? [])].map((s) => s.scenario))];
  return (
    <Table>
      <thead>
        <tr>
          <Th>Scenario</Th>
          <Th num className="max-sm:hidden">Cases</Th>
          <Th>Right answer</Th>
          <Th num>Rules-only</Th>
          <Th num className="pl-6">StormDesk</Th>
        </tr>
      </thead>
      <tbody>
        {names.map((name, i) => {
          const r = rules?.per_scenario.find((s) => s.scenario === name);
          const s = desk?.per_scenario.find((x) => x.scenario === name);
          const info = (r ?? s)!;
          return (
            <tr key={name}>
              <Td className="text-heading">{SCENARIO_LABEL[name] ?? name}</Td>
              <Td num className="max-sm:hidden">{info.rows}</Td>
              <Td className="text-secondary">{info.honest ? "Leave alone" : (ACTION_PLAIN[info.label_action] ?? info.label_action)}</Td>
              <Td num className={info.honest && r?.dismissed === 0 ? "text-danger" : undefined}>
                {scenarioCell(r) ?? "No run yet"}
              </Td>
              {desk ? (
                <Td num className={`pl-6 font-medium ${info.honest && s?.dismissed === 0 ? "text-danger" : "text-heading"}`}>
                  {scenarioCell(s) ?? "n/a"}
                </Td>
              ) : (
                i === 0 && <NoStormDesk rows={names.length} />
              )}
            </tr>
          );
        })}
      </tbody>
    </Table>
  );
}

function TrapRow({ row, open }: { row: EvalRow; open: boolean }) {
  return (
    <details open={open} className="border-b border-rule py-2.5">
      <summary className="cursor-pointer text-heading">
        {row.subject_name ?? row.subject_id} · {SCENARIO_LABEL[row.label_scenario] ?? row.label_scenario} · seed{" "}
        {row.seed} · left alone ({row.output_kind ? (KIND_PLAIN[row.output_kind] ?? row.output_kind).toLowerCase() : "no flag"},{" "}
        {row.output_action ? (ACTION_PLAIN[row.output_action] ?? row.output_action).toLowerCase() : "no action"})
      </summary>
      {row.summary && <p className="mt-2 max-w-[90ch] text-ink">{row.summary}</p>}
      {row.reasoning && <p className="mt-2 max-w-[90ch] whitespace-pre-wrap text-secondary">{row.reasoning}</p>}
      {row.evidence_ids.length > 0 && (
        <p className="mt-2 break-all font-mono text-th text-secondary">Evidence: {row.evidence_ids.join(", ")}</p>
      )}
    </details>
  );
}

function Traps({ rules, desk }: { rules: EvalRun | null; desk: EvalRun | null }) {
  const right = desk ? trapsRight(desk) : [];
  return (
    <Section title="Trap cases StormDesk got right">
      {!desk && (
        <p className="py-2.5 text-secondary">
          Appears with the first StormDesk run.
          {rules &&
            ` The rules-only baseline left ${trapsRight(rules).length} of ${rules.dataset.honest_rows} traps alone: it flags every one.`}
        </p>
      )}
      {desk && right.length === 0 && (
        <p className="py-2.5 text-secondary">None: it flagged every honest subject in the dataset.</p>
      )}
      {desk && right.length > 0 && (
        <div>
          <p className="py-2 text-secondary">
            {right.length} of {desk.dataset.honest_rows} traps left alone.
          </p>
          <div className="border-t border-rule">
            {right.map((row, i) => (
              <TrapRow key={row.row_id} row={row} open={i === 0} />
            ))}
          </div>
        </div>
      )}
    </Section>
  );
}

/** The few numbers a judge should read first, big, from the scored runs only. */
function BigFacts({ rules, desk }: { rules: EvalRun | null; desk: EvalRun | null }) {
  if (!desk) return null;
  const df = desk.metrics.honest_flagged;
  const dc = desk.metrics.real_caught;
  const cv = desk.metrics.citations_valid;
  return (
    <Strip big items={[
      { label: "Honest cases wrongly flagged", value: `${df.flagged} of ${df.total}`,
        sub: rules ? `Rules alone: ${rules.metrics.honest_flagged.flagged} of ${rules.metrics.honest_flagged.total}` : undefined },
      { label: "Real cases caught", value: `${dc.caught} of ${dc.total}`,
        sub: rules ? `Rules alone: ${rules.metrics.real_caught.caught} of ${rules.metrics.real_caught.total}` : undefined },
      ...(cv ? [{ label: "Answers that only cite real records", value: `${cv.valid} of ${cv.checked}`, sub: desk.model ?? undefined }] : []),
    ]} />
  );
}

/** One scored section: the big numbers, the strip, the comparison, the scenarios, then the two runs. */
function Scored({ section, heldout, children }: { section: EvalSection; heldout: boolean; children?: ReactNode }) {
  const { rules_only: rules, stormdesk: desk } = section.columns;
  return (
    <div className="space-y-10">
      <BigFacts rules={rules} desk={desk} />
      <SectionStrip rules={rules} desk={desk} heldout={heldout} />
      {heldout && (
        <p className="-mt-6 max-w-[90ch] text-secondary">
          Chosen before the run and never seen while the prompt was written, scored apart from the main dataset.
        </p>
      )}
      <Comparison rules={rules} desk={desk} />
      <Section title="By scenario">
        <Scenarios rules={rules} desk={desk} />
      </Section>
      {children}
      <details>
        <summary className="cursor-pointer py-1 text-accent">Run details</summary>
        <div className="mt-4 grid gap-10 lg:grid-cols-2">
          <RunFacts title="Rules-only baseline" run={rules}
            empty={heldout ? "No rules-only run on these rows yet." : "No rules-only run yet."} />
          <RunFacts title="StormDesk (Droid)" run={desk}
            empty={heldout ? "No StormDesk run on the held-out seeds yet." : "No StormDesk run yet."} />
        </div>
      </details>
    </div>
  );
}

export function EvalsTab() {
  const [data, setData] = useState<EvalsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View | null>(null);

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

  const heldout = data?.heldout;
  const heldoutShown = heldout && (heldout.columns.stormdesk ?? heldout.columns.rules_only);
  // Held-out towns first when they exist; otherwise open on the main dataset.
  const current: View = view ?? (data && !heldoutShown ? "main" : "heldout");
  const { rules_only: rules, stormdesk: desk } = data?.columns ?? { rules_only: null, stormdesk: null };
  const shown = rules ?? desk;
  const others = data ? [...data.other_runs, ...(data.heldout?.other_runs ?? [])] : [];

  return (
    <div className="pb-12">
      <PageHeader title="How good is the agent?" subtitle="StormDesk measured with Chalk Evaluations on labeled simulated towns"
        takeaway={data ? (heldoutShown
          ? evalsTakeaway(heldout!.columns.rules_only, heldout!.columns.stormdesk, true)
          : evalsTakeaway(rules, desk, false)) ?? undefined : undefined}>
        <Tabs tabs={VIEWS} value={current} onChange={setView} />
      </PageHeader>
      {error && !data && <Note tone="danger">Couldn't load the eval results: {error}</Note>}
      {!data && !error && <Note>Loading eval results…</Note>}

      {data && current === "heldout" && (
        <div className="space-y-10">
          {heldout && heldoutShown ? <Scored section={heldout} heldout /> : <p className="text-section text-ink">No held-out run yet.</p>}
          <AuthorPanel dev={desk} heldout={heldout?.columns.stormdesk ?? null} />
        </div>
      )}

      {data && current === "main" && (
        !shown ? (
          <p className="text-section text-ink">No eval run yet.</p>
        ) : (
          <Scored section={data} heldout={false}>
            <Traps rules={rules} desk={desk} />
            {shown.dataset.detector_misses.length > 0 && (
              <Section title="Not in the dataset">
                <p className="py-2 text-secondary">
                  {shown.dataset.detector_misses.length} planted cheats and look-alikes never raised a suspicion, so neither side saw
                  them (they aren't counted above):
                </p>
                <ul className="border-t border-rule">
                  {shown.dataset.detector_misses.map((m) => (
                    <li key={`${m.seed}:${m.subject_id}`} className="border-b border-rule py-2 text-ink">
                      {m.name} · {SCENARIO_LABEL[m.scenario] ?? m.scenario} · seed {m.seed}
                    </li>
                  ))}
                </ul>
              </Section>
            )}
          </Scored>
        )
      )}

      {data && current === "runs" && (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-secondary">
              {data.runs_found} saved results files. Runs that aren't scored are listed with the reason, never with
              their numbers.
            </p>
            <Button onClick={load}>Reload results</Button>
          </div>
          {others.length === 0 ? (
            <p className="text-secondary">No other saved runs.</p>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>When</Th>
                  <Th>Why it isn't scored</Th>
                  <Th>How</Th>
                  <Th>Chalk run</Th>
                </tr>
              </thead>
              <tbody>
                {others.map((r) => (
                  <tr key={r.file}>
                    <Td className="whitespace-nowrap text-secondary">{r.timestamp ? when(r.timestamp) : r.file}</Td>
                    <Td className="text-ink">{plainLabel(r.reason)}</Td>
                    <Td className="text-secondary">{r.mode ? (MODE_LABEL[r.mode] ?? r.mode) : "—"}</Td>
                    <Td>{r.chalk_run_id ? <ChalkId id={r.chalk_run_id} /> : <span className="text-secondary">—</span>}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
          {data.errors.length > 0 && (
            <p className="text-danger">Couldn't read: {data.errors.map((e) => `${e.file} (${e.error})`).join("; ")}</p>
          )}
        </div>
      )}
    </div>
  );
}
