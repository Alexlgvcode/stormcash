// StormDesk on the dashboard (spec §18.3, §14.6, §14.7b, §14.8): the review
// queue of flags with their evidence, the agent's tool calls live or replayed,
// the reviewer's second opinion, Approve / Reject with the operator's name, and
// the Photon thread for merchant flags, where each StormDesk reply says which
// turn of the appeal's Droid session wrote it (§17.2). A fake-runner result is
// labelled as such everywhere (§0 rule 3).
import { useCallback, useEffect, useRef, useState } from "react";
import { getJSON, operatorPost, type FlagDetail, type FlagRow, type Message, type Run, type Step, type Usage } from "../api";
import { heldBack, sessionSummary, turnLabel, turnsByReply, type AppealTurn } from "../appeal";
import { useEvents } from "../events";
import { clockTime, dollars } from "../format";
import { ACTION_PLAIN, KIND_PLAIN, SEVERITY_PLAIN, toolPlain } from "../plain";
import { reviewVerdict, suggestion, type FlagReview } from "../review";
import { OwnerFreezeNote } from "./OwnerFreeze";
import { Button, Eyebrow, Note, Pill, Section, Table, Td, TextInput, Th, type Tone } from "./ui";

const KIND_TITLE = KIND_PLAIN;
const ACTION_TITLE = ACTION_PLAIN;

const SEVERITY_TONE: Record<string, Tone> = { urgent: "danger", review: "warning", info: "neutral" };

/** The queue's status column: what a person has to do with this flag. */
function flagStatus(f: FlagRow): { tone: Tone; text: string } {
  if (f.status === "open" && f.agents_disagree) return { tone: "agents", text: "Agents disagree" };
  switch (f.status) {
    case "open":
      return { tone: "warning", text: "Needs a person" };
    case "approved":
      return { tone: "success", text: "Approved" };
    case "invalid":
      return { tone: "danger", text: "Invalid" };
    default:
      return { tone: "neutral", text: f.status === "rejected" ? "Rejected" : "Dismissed" };
  }
}

/** "Replay of run at 09:23:23 · Droid, claude-sonnet-5-5": a replay always says what produced it. */
export function replayTitle(startedAt: number, runner: string | null | undefined, model?: string | null): string {
  const by = runner === "fake" ? "rules-only stand-in" : runner === "droid" ? `Droid, ${model ?? "model not recorded"}` : runner;
  return `Replay of run at ${clockTime(startedAt)}${by ? ` · ${by}` : ""}`;
}

export function RunnerBadge({ runner, model, modelRequested, usage }: {
  runner: string | null | undefined;
  model?: string | null;
  modelRequested?: string | null;
  usage?: Usage | null;
}) {
  if (runner === "fake") {
    return (
      <Pill tone="warning" title="A deterministic rules-only stand-in answered, not an agent's judgement.">
        Rules-only stand-in
      </Pill>
    );
  }
  if (runner === "droid") {
    const tokens = usage ? (usage.input_tokens ?? 0) + (usage.output_tokens ?? 0) : null;
    const switched = model && modelRequested && modelRequested !== "auto" && model !== modelRequested;
    const parts = ["Droid", model && model !== "auto" ? model : null, switched ? `asked for ${modelRequested}` : null,
      usage?.factory_credits != null ? `${Math.round(usage.factory_credits).toLocaleString("en-US")} credits` : null];
    return (
      <Pill tone="neutral"
        title={tokens != null ? `${tokens.toLocaleString("en-US")} tokens in + out (cache reads ${(usage?.cache_read_tokens ?? 0).toLocaleString("en-US")})` : undefined}>
        {parts.filter(Boolean).join(" · ")}
      </Pill>
    );
  }
  return null;
}

/** Tool-call steps, live or replayed one by one (§14.8). */
export function StepList({ steps, live, replayLabel }: { steps: Step[]; live?: boolean; replayLabel?: string }) {
  const [shown, setShown] = useState<number>(steps.length);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => setShown(steps.length), [steps.length]);
  useEffect(() => () => {
    if (timer.current) clearInterval(timer.current);
  }, []);

  function replay() {
    if (timer.current) clearInterval(timer.current);
    setShown(0);
    let n = 0;
    timer.current = setInterval(() => {
      n += 1;
      setShown(n);
      if (n >= steps.length && timer.current) clearInterval(timer.current);
    }, 700);
  }

  return (
    <div>
      <div className="flex items-center justify-between gap-3 py-1.5">
        <span className="flex items-center gap-2 text-th text-secondary">
          {live && <span className="h-2 w-2 animate-pulse rounded-full bg-accent" />}
          {live ? "Live tool calls" : (replayLabel ?? "Tool calls")}
        </span>
        {!live && steps.length > 0 && (
          <Button small onClick={replay}>
            Replay
          </Button>
        )}
      </div>
      {steps.length === 0 && <p className="border-t border-rule py-2.5 text-secondary">No tool calls.</p>}
      <ol className="border-t border-rule">
        {steps.slice(0, shown).map((s) => (
          <li key={s.index} title={`${s.tool} ${s.input_summary}`}
            className="grid grid-cols-[1.25rem_minmax(0,1fr)] items-baseline gap-3 border-b border-rule py-2">
            <span className={s.ok === null ? "text-secondary" : s.ok ? "text-success" : "text-danger"}>
              {s.ok === null ? "…" : s.ok ? "✓" : "✗"}
            </span>
            <span className="text-ink">{toolPlain(s.tool)}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** Steps arriving over SSE for one job subject ("case #3" / "candidate #7"). */
export function useLiveSteps(subject: string) {
  const [steps, setSteps] = useState<Step[]>([]);
  const [running, setRunning] = useState(false);
  useEvents(["stormdesk_step"], (data) => {
    const d = data as Step & { subject: string; done?: boolean };
    if (d.subject !== subject) return;
    if (d.done) {
      setRunning(false);
      return;
    }
    setRunning(true);
    setSteps((cur) => {
      const next = cur.filter((s) => s.index !== d.index);
      return [...next, { index: d.index, tool: d.tool, input_summary: d.input_summary, ok: d.ok }].sort(
        (a, b) => a.index - b.index);
    });
  });
  const reset = useCallback(() => setSteps([]), []);
  return { steps, running, reset };
}

function operatorName(): string {
  try {
    return localStorage.getItem("sc-operator") ?? "";
  } catch {
    return "";
  }
}

/** Evidence ids, each marked as found in the database or not. */
function CitedIds({ ids, missing }: { ids: string[]; missing: string[] }) {
  if (ids.length === 0) return <p className="py-2.5 text-secondary">None cited.</p>;
  return (
    <ul>
      {ids.map((e) => {
        const bad = missing.includes(e);
        return (
          <li key={e} className="flex items-baseline justify-between gap-4 border-b border-rule py-2">
            <span className="min-w-0 truncate font-mono text-th text-ink" title={e}>
              {e.length > 28 ? `${e.slice(0, 24)}…` : e}
            </span>
            <span className={`whitespace-nowrap text-th ${bad ? "text-danger" : "text-success"}`}>
              {bad ? "not in the database ✗" : "checked ✓"}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function PhotonThread({ merchantId }: { merchantId: string }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [turns, setTurns] = useState<AppealTurn[]>([]);
  const load = useCallback(() => {
    getJSON<{ messages: Message[]; turns?: AppealTurn[] }>(`/v1/photon/messages?merchant_id=${merchantId}`)
      .then((r) => {
        setMessages(r.messages);
        setTurns(r.turns ?? []);
      })
      .catch(() => setMessages([]));
  }, [merchantId]);
  useEffect(load, [load]);
  useEvents(["message"], (data) => {
    if ((data as Message).merchant_id === merchantId) setMessages((cur) => [...cur, data as Message]);
  });
  useEvents(["appeal"], (data) => {
    if ((data as { merchant_id?: string }).merchant_id === merchantId) load(); // the turn that just answered
  });
  const byReply = turnsByReply(turns);
  const summary = sessionSummary(turns);
  return (
    <Section
      title="Photon thread"
      right={
        summary && (
          <span title="Every reply in this appeal is a turn of the same Droid conversation, picked up again for each new text.">
            <Pill tone="success">{summary}</Pill>
          </span>
        )
      }
    >
      {messages.length === 0 && <p className="py-2.5 text-secondary">No messages with this shop.</p>}
      <ol>
        {messages.map((m) => {
          const turn = m.direction === "out" ? byReply.get(m.message_id) : undefined;
          const held = turn ? heldBack(turn) : null;
          const out = m.direction === "out";
          return (
            <li key={m.message_id} className="grid grid-cols-[8.5rem_minmax(0,1fr)] gap-4 border-b border-rule py-3">
              <div className="text-th text-secondary">
                <div className={`font-medium ${out ? "text-accent" : "text-heading"}`}>{out ? "StormCash" : "Shop"}</div>
                <div className="tabular-nums">{clockTime(m.created_at)}</div>
                <div>{m.channel}</div>
              </div>
              <div className="min-w-0">
                <p className="whitespace-pre-wrap break-words text-ink">{m.body}</p>
                {(turn || held || m.delivered === false) && (
                  <div className="mt-1.5 flex flex-wrap items-center gap-2 text-th">
                    {turn && (
                      <Pill tone={turn.runner === "fake" ? "warning" : turn.session === "resumed" ? "success" : "neutral"}>
                        {turnLabel(turn)}
                      </Pill>
                    )}
                    {held && <span className="text-danger">{held}</span>}
                    {m.delivered === false && <span className="text-secondary">not delivered</span>}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </Section>
  );
}

const VERDICT_TONE: Record<string, Tone> = { agree: "success", disagree: "agents", void: "danger" };

/** The reviewer Droid's second opinion (§14.7b): verdict, reasons, the records it cited, its own steps. */
function ReviewPanel({ flag, review, run, live, onReview }: {
  flag: FlagRow;
  review: FlagReview | null | undefined;
  run: Run | null;
  live: { steps: Step[]; running: boolean };
  onReview: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const reviewable = flag.status === "open" || flag.status === "dismissed";
  const view = review ? reviewVerdict(review) : null;
  const suggested = review ? suggestion(review, KIND_TITLE, ACTION_TITLE) : null;

  async function ask() {
    setBusy(true);
    try {
      await operatorPost("/v1/stormdesk/review", { flag_id: flag.flag_id });
    } catch {
      // shown by the reload: the flag keeps its last review
    } finally {
      setBusy(false);
      onReview();
    }
  }

  if (!review && !live.running && live.steps.length === 0 && !reviewable) return null;
  return (
    <Section
      title="Second opinion"
      right={
        reviewable && (
          <Button small disabled={busy || live.running} onClick={ask}>
            {busy || live.running ? "Reviewing…" : review ? "Review again" : "Ask the reviewer"}
          </Button>
        )
      }
    >
      <div className="space-y-3 pt-2">
        {(view || review) && (
          <div className="flex flex-wrap items-center gap-2">
            {view && <Pill tone={VERDICT_TONE[view.tone]}>{view.label}</Pill>}
            {review && (
              <RunnerBadge runner={review.runner} model={review.model} modelRequested={review.model_requested} usage={review.usage} />
            )}
          </div>
        )}
        {!review && !live.running && (
          <p className="text-secondary">
            Not reviewed yet. A second Droid session re-reads the records with the same read-only tools and tries to
            refute StormDesk's proposal.
          </p>
        )}
        {view?.note && <p className="text-secondary">{view.note}</p>}
        {review?.error && <p className="break-all font-mono text-th text-danger">{review.error}</p>}
        {review?.reasons && review.reasons.length > 0 && (
          <ul className="list-disc space-y-1 pl-5 text-ink">
            {review.reasons.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        )}
        {suggested && <p className="text-ink">{suggested}</p>}
      </div>
      {review && (
        <div className="mt-5 grid gap-10 lg:grid-cols-2">
          <div>
            <div className="py-1.5 text-th text-secondary">
              Records it cited {review.citations_valid ? "· checked against the database ✓" : "· citation check failed ✗"}
            </div>
            <div className="border-t border-rule">
              <CitedIds ids={review.evidence_ids ?? []} missing={review.missing_citations} />
            </div>
          </div>
          <div>
            {live.steps.length > 0 || live.running ? (
              <StepList steps={live.steps} live />
            ) : (
              run?.transcript && (
                <StepList steps={run.transcript.steps} replayLabel={replayTitle(run.started_at, run.runner, run.transcript.model)} />
              )
            )}
          </div>
        </div>
      )}
      {!review && (live.steps.length > 0 || live.running) && (
        <div className="mt-4">
          <StepList steps={live.steps} live />
        </div>
      )}
    </Section>
  );
}

function FlagView({ flagId, onChanged }: { flagId: number; onChanged: () => void }) {
  const [detail, setDetail] = useState<FlagDetail | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [reviewRun, setReviewRun] = useState<Run | null>(null);
  const [showReasoning, setShowReasoning] = useState(false);
  const [operator, setOperator] = useState(operatorName);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const load = useCallback(() => {
    getJSON<FlagDetail>(`/v1/flags/${flagId}`).then((d) => {
      setDetail(d);
      if (d.agent?.run_id) getJSON<Run>(`/v1/stormdesk/runs/${d.agent.run_id}`).then(setRun).catch(() => setRun(null));
      const reviewId = d.flag.review?.run_id;
      if (reviewId) getJSON<Run>(`/v1/stormdesk/runs/${reviewId}`).then(setReviewRun).catch(() => setReviewRun(null));
      else setReviewRun(null);
    });
  }, [flagId]);
  useEffect(() => {
    setResult(null);
    setShowReasoning(false);
    load();
  }, [load]);
  const live = useLiveSteps(detail ? `candidate #${detail.flag.candidate_id}` : "");
  const liveReview = useLiveSteps(detail ? `review of candidate #${detail.flag.candidate_id}` : "");
  useEvents(["flag", "approval"], (data) => {
    const d = data as { flag_id?: number };
    if (d.flag_id === flagId) {
      live.reset();
      liveReview.reset();
      load();
    }
  });

  if (!detail) return <Note>Loading flag…</Note>;
  const { flag, agent } = detail;
  const merchantFlag = flag.kind === "merchant_silence" || flag.proposed_action === "hold_pool_payout"
    || flag.proposed_action === "lower_merchant_limit";
  const certFlag = detail.candidate?.kind === "cap_drain" || flag.proposed_action === "freeze_cert";
  const actionable = flag.status === "open" && flag.citations_valid;
  const status = flagStatus(flag);

  async function rerun() {
    live.reset();
    liveReview.reset();
    await operatorPost("/v1/stormdesk/run", { candidate_id: flag.candidate_id }).catch(() => undefined);
    load();
    onChanged();
  }

  async function decide(verb: "approve" | "reject") {
    if (!operator.trim()) {
      setResult("Type your name first: every decision is signed by a person.");
      return;
    }
    try {
      localStorage.setItem("sc-operator", operator.trim());
    } catch {
      // private window: fine
    }
    setBusy(true);
    try {
      const body = await operatorPost<{ executed_actions: Record<string, unknown> }>(
        `/v1/flags/${flag.flag_id}/${verb}`, { note: note || null }, operator.trim());
      setResult(verb === "approve" ? `Approved: ${JSON.stringify(body.executed_actions)}` : "Rejected: nothing ran.");
      load();
      onChanged();
    } catch (e) {
      setResult(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-10">
      <div>
        <Eyebrow>
          {flag.subject_name ?? flag.subject_id} · proposed by {flag.runner === "fake" ? "the rules-only stand-in" : "StormDesk"} · flag #
          {flag.flag_id}
        </Eyebrow>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h2 className="text-[22px] leading-8 font-semibold text-heading">
            {ACTION_TITLE[flag.proposed_action] ?? flag.proposed_action}
          </h2>
          <Pill tone={SEVERITY_TONE[flag.severity] ?? "neutral"}>{SEVERITY_PLAIN[flag.severity] ?? flag.severity}</Pill>
          <RunnerBadge runner={flag.runner} model={agent?.model} modelRequested={agent?.model_requested} usage={agent?.usage} />
          {flag.agents_disagree && (
            <span title="A second Droid session reviewed StormDesk's proposal and didn't agree. A person decides.">
              <Pill tone="agents">Agents disagree · a person decides</Pill>
            </span>
          )}
          <div className="ml-auto flex items-center gap-2">
            {actionable ? (
              <>
                <Button disabled={busy} onClick={() => decide("reject")}>
                  Reject
                </Button>
                <Button primary disabled={busy} onClick={() => decide("approve")}>
                  Approve
                </Button>
              </>
            ) : (
              <Pill tone={status.tone}>{status.text}</Pill>
            )}
          </div>
        </div>
        <p className="mt-3 max-w-[80ch] text-ink">
          {flag.subject_name ?? flag.subject_id}: {flag.summary}
        </p>
        <p className="mt-1 text-secondary">
          {KIND_TITLE[flag.kind] ?? flag.kind}
          {flag.exposure_cents > 0 && ` · Exposure ${dollars(flag.exposure_cents)}`}
        </p>
        {actionable ? (
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <span className="text-secondary">Signed by</span>
            <TextInput value={operator} onChange={(e) => setOperator(e.target.value)} placeholder="Operator name" />
            <TextInput value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (optional)" className="min-w-64" />
          </div>
        ) : (
          flag.status === "invalid" && (
            <p className="mt-3 text-secondary">Not actionable: a cited id doesn't exist or there was no valid output.</p>
          )
        )}
        {flag.agents_disagree && actionable && (
          <p className="mt-3 max-w-[80ch] text-accent">
            StormDesk and its reviewer disagree. Read both, then decide: Approve runs StormDesk's proposal and nothing
            else. The reviewer can't act.
          </p>
        )}
        {result && <p className="mt-3 break-all font-mono text-th text-ink">{result}</p>}
        {certFlag && (
          <div className="mt-4">
            <OwnerFreezeNote certId={flag.subject_id}
              seenByDetector={detail.candidate?.features?.owner_freeze_request === true} />
          </div>
        )}
        {agent?.reasoning && (
          <div className="mt-3">
            <button onClick={() => setShowReasoning((v) => !v)} className="text-accent hover:underline">
              {showReasoning ? "Hide reasoning" : "Show reasoning"}
            </button>
            {showReasoning && <p className="mt-2 max-w-[80ch] whitespace-pre-wrap text-ink">{agent.reasoning}</p>}
          </div>
        )}
      </div>

      <div className="grid gap-10 lg:grid-cols-2">
        <Section title="Evidence"
          right={<span className={`text-th ${flag.citations_valid ? "text-success" : "text-danger"}`}>
            {flag.citations_valid ? "every id checked ✓" : "citation check failed ✗"}
          </span>}>
          <CitedIds ids={flag.evidence_ids} missing={agent?.missing_citations ?? []} />
        </Section>
        <Section title="Agent steps" right={<Button small onClick={rerun}>Run StormDesk again</Button>}>
          {live.steps.length > 0 || live.running ? (
            <StepList steps={live.steps} live />
          ) : (
            <StepList steps={agent?.steps ?? []}
              replayLabel={run ? replayTitle(run.started_at, agent?.runner ?? flag.runner, agent?.model) : undefined} />
          )}
        </Section>
      </div>

      <ReviewPanel flag={flag} review={flag.review} run={reviewRun} live={liveReview} onReview={() => {
        liveReview.reset();
        load();
        onChanged();
      }} />
      {merchantFlag && <PhotonThread merchantId={flag.subject_id} />}
    </div>
  );
}

function secondOpinion(f: FlagRow): string {
  return f.review ? reviewVerdict(f.review).label : "Not reviewed";
}

/** The review queue: every flag, then the selected one in full. */
export function FlagsView() {
  const [flags, setFlags] = useState<FlagRow[] | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const load = useCallback(() => {
    getJSON<FlagRow[]>("/v1/flags?limit=200").then((rows) => {
      setFlags(rows);
      setSelected((cur) => cur ?? rows.find((r) => r.status === "open")?.flag_id ?? rows[0]?.flag_id ?? null);
    });
  }, []);
  useEffect(load, [load]);
  useEvents(["flag", "approval", "town"], load);

  if (!flags) return <Note>Loading…</Note>;
  if (flags.length === 0) return <Note>No StormDesk flags yet. They appear as soon as a detector fires.</Note>;
  return (
    <div className="space-y-10">
      <div className="max-h-[22rem] overflow-y-auto">
        <Table>
          <thead className="sticky top-0 bg-page">
            <tr>
              <Th className="pl-3">Subject</Th>
              <Th>Signal</Th>
              <Th num>Exposure</Th>
              <Th>Second opinion</Th>
              <Th>Status</Th>
            </tr>
          </thead>
          <tbody>
            {flags.map((f) => {
              const status = flagStatus(f);
              const on = selected === f.flag_id;
              return (
                <tr key={f.flag_id} onClick={() => setSelected(f.flag_id)} aria-selected={on}
                  className={`cursor-pointer ${on ? "bg-accent-tint" : "hover:bg-accent-tint/50"}`}>
                  <Td className={`pl-3 ${on ? "font-semibold text-heading" : "text-heading"}`}>{f.subject_name ?? f.subject_id}</Td>
                  <Td>{KIND_TITLE[f.kind] ?? f.kind}</Td>
                  <Td num>{f.exposure_cents > 0 ? dollars(f.exposure_cents) : <span className="text-secondary">—</span>}</Td>
                  <Td className="text-secondary">{secondOpinion(f)}</Td>
                  <Td className="pr-3">
                    <span className="flex flex-wrap gap-1.5">
                      <Pill tone={status.tone}>{status.text}</Pill>
                      {f.runner === "fake" && <Pill tone="warning">Stand-in</Pill>}
                    </span>
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      </div>
      {selected !== null && <FlagView key={selected} flagId={selected} onChanged={load} />}
    </div>
  );
}

/** StormDesk's runs on one hard case: run it now, watch it live, replay the last run. */
export function CaseStormDesk({ caseId, onFiled }: { caseId: number; onFiled: () => void }) {
  const [run, setRun] = useState<Run | null>(null);
  const [busy, setBusy] = useState(false);
  const live = useLiveSteps(`case #${caseId}`);
  const load = useCallback(() => {
    getJSON<Run[]>(`/v1/stormdesk/runs?case_id=${caseId}&limit=1`).then((runs) => {
      if (runs[0]) getJSON<Run>(`/v1/stormdesk/runs/${runs[0].run_id}`).then(setRun);
      else setRun(null);
    });
  }, [caseId]);
  const { reset } = live;
  useEffect(() => {
    reset();
    load();
  }, [load, reset]);

  async function start() {
    setBusy(true);
    live.reset();
    try {
      await operatorPost("/v1/stormdesk/run", { case_id: caseId });
    } finally {
      setBusy(false);
      load();
      onFiled();
    }
  }

  return (
    <Section
      title="StormDesk"
      right={
        <Button small disabled={busy} onClick={start}>
          {busy ? "Investigating…" : run ? "Investigate again" : "Investigate"}
        </Button>
      }
    >
      {run && (
        <div className="flex flex-wrap items-center gap-2 py-2">
          <RunnerBadge runner={run.runner} model={run.transcript?.model} modelRequested={run.transcript?.model_requested}
            usage={run.transcript?.usage} />
          <span className="text-th text-secondary">last run {clockTime(run.started_at)} · {run.status}</span>
        </div>
      )}
      {live.steps.length > 0 || live.running ? (
        <StepList steps={live.steps} live />
      ) : run?.transcript ? (
        <StepList steps={run.transcript.steps} replayLabel={replayTitle(run.started_at, run.runner, run.transcript.model)} />
      ) : (
        <p className="py-2.5 text-secondary">StormDesk hasn't investigated this case yet.</p>
      )}
    </Section>
  );
}
