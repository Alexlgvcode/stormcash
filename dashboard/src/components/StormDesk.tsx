// StormDesk on the dashboard (spec §18.3, §14.6, §14.8): flags with their
// evidence, the agent's tool calls live or replayed, Approve / Reject with the
// operator's name, and the Photon thread for merchant flags. A fake-runner
// result is labelled as such everywhere (§0 rule 3).
import { useCallback, useEffect, useRef, useState } from "react";
import { getJSON, operatorPost, type FlagDetail, type FlagRow, type Message, type Run, type Step } from "../api";
import { useEvents } from "../events";
import { clockTime, dollars } from "../format";

const KIND_TITLE: Record<string, string> = {
  merchant_silence: "Shop went quiet",
  cap_drain: "Certificate drained fast",
  region_dark: "Region went dark",
  none: "Dismissed",
};

const ACTION_TITLE: Record<string, string> = {
  hold_pool_payout: "Hold guarantee-pool payouts",
  lower_merchant_limit: "Lower the shop's per-payment limit",
  freeze_cert: "Freeze the certificate",
  dispatch_relay: "Send a relay",
  none: "No action",
};

const STATUS_STYLE: Record<string, string> = {
  open: "bg-sky-500/15 text-sky-300",
  approved: "bg-emerald-500/15 text-emerald-300",
  rejected: "bg-slate-500/20 text-slate-300",
  dismissed: "bg-slate-500/20 text-slate-300",
  invalid: "bg-rose-500/15 text-rose-300",
};

export function RunnerBadge({ runner }: { runner: string | null | undefined }) {
  if (runner === "fake") {
    return (
      <span className="rounded-full bg-amber-500/15 px-3 py-1 text-sm font-semibold text-amber-300"
        title="No Factory access yet: a deterministic rules-only stand-in, not an agent's judgement.">
        Fake runner · rules only
      </span>
    );
  }
  if (runner === "droid") {
    return <span className="rounded-full bg-violet-500/15 px-3 py-1 text-sm font-semibold text-violet-300">Droid</span>;
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
    <div className="rounded-xl border border-slate-800 bg-slate-950 p-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-base font-semibold text-slate-200">
          {live ? "Live tool calls" : shown < steps.length || replayLabel ? (replayLabel ?? "Tool calls") : "Tool calls"}
        </span>
        {!live && steps.length > 0 && (
          <button onClick={replay} className="rounded-lg bg-slate-800 px-3 py-1 text-sm text-slate-200 hover:bg-slate-700">
            Replay
          </button>
        )}
      </div>
      {steps.length === 0 && <p className="text-slate-500">No tool calls.</p>}
      <ol className="space-y-1 font-mono text-sm">
        {steps.slice(0, shown).map((s) => (
          <li key={s.index} className="flex gap-2">
            <span className={s.ok === null ? "text-slate-400" : s.ok ? "text-emerald-400" : "text-rose-400"}>
              {s.ok === null ? "…" : s.ok ? "✓" : "✗"}
            </span>
            <span className="text-sky-300">{s.tool}</span>
            <span className="truncate text-slate-500">{s.input_summary}</span>
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

function Decision({ flag, onDone }: { flag: FlagRow; onDone: () => void }) {
  const [operator, setOperator] = useState(operatorName);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const actionable = flag.status === "open" && flag.citations_valid;

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
      onDone();
    } catch (e) {
      setResult(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3 rounded-xl border border-slate-700 bg-slate-900 p-4">
      <div className="text-base text-slate-300">
        Proposed: <span className="font-semibold text-white">{ACTION_TITLE[flag.proposed_action] ?? flag.proposed_action}</span>
      </div>
      {actionable ? (
        <>
          <div className="grid gap-2 sm:grid-cols-2">
            <input value={operator} onChange={(e) => setOperator(e.target.value)} placeholder="Operator name"
              className="rounded-lg bg-slate-800 px-3 py-2 text-base text-white placeholder:text-slate-500" />
            <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (optional)"
              className="rounded-lg bg-slate-800 px-3 py-2 text-base text-white placeholder:text-slate-500" />
          </div>
          <div className="flex gap-3">
            <button disabled={busy} onClick={() => decide("approve")}
              className="flex-1 rounded-xl bg-emerald-500 py-3 text-lg font-bold text-slate-950 hover:bg-emerald-400 disabled:opacity-50">
              Approve
            </button>
            <button disabled={busy} onClick={() => decide("reject")}
              className="flex-1 rounded-xl bg-slate-700 py-3 text-lg font-bold text-white hover:bg-slate-600 disabled:opacity-50">
              Reject
            </button>
          </div>
        </>
      ) : (
        <p className="text-slate-400">
          {flag.status === "invalid" ? "Not actionable: a cited id doesn't exist or there was no valid output."
            : `This flag is ${flag.status}.`}
        </p>
      )}
      {result && <p className="break-all font-mono text-sm text-slate-300">{result}</p>}
    </div>
  );
}

function PhotonThread({ merchantId }: { merchantId: string }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const load = useCallback(() => {
    getJSON<{ messages: Message[] }>(`/v1/photon/messages?merchant_id=${merchantId}`)
      .then((r) => setMessages(r.messages))
      .catch(() => setMessages([]));
  }, [merchantId]);
  useEffect(load, [load]);
  useEvents(["message"], (data) => {
    if ((data as Message).merchant_id === merchantId) setMessages((cur) => [...cur, data as Message]);
  });
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950 p-4">
      <h4 className="mb-2 text-base font-semibold text-slate-200">Photon thread</h4>
      {messages.length === 0 && <p className="text-slate-500">No messages with this shop.</p>}
      <ol className="space-y-2">
        {messages.map((m) => (
          <li key={m.message_id} className={`flex ${m.direction === "out" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[85%] rounded-2xl px-3 py-2 text-base ${
              m.direction === "out" ? "bg-sky-600/30 text-sky-50" : "bg-slate-800 text-slate-100"}`}>
              {m.body}
              <div className="mt-1 text-xs text-slate-400">
                {m.direction === "out" ? "StormCash" : "Shop"} · {m.channel} · {clockTime(m.created_at)}
                {m.delivered === false && " · not delivered"}
              </div>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

function FlagView({ flagId, onChanged }: { flagId: number; onChanged: () => void }) {
  const [detail, setDetail] = useState<FlagDetail | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [showReasoning, setShowReasoning] = useState(false);
  const load = useCallback(() => {
    getJSON<FlagDetail>(`/v1/flags/${flagId}`).then((d) => {
      setDetail(d);
      if (d.agent?.run_id) getJSON<Run>(`/v1/stormdesk/runs/${d.agent.run_id}`).then(setRun).catch(() => setRun(null));
    });
  }, [flagId]);
  useEffect(load, [load]);
  const live = useLiveSteps(detail ? `candidate #${detail.flag.candidate_id}` : "");
  useEvents(["flag", "approval"], (data) => {
    const d = data as { flag_id?: number };
    if (d.flag_id === flagId) {
      live.reset();
      load();
    }
  });

  if (!detail) return <p className="text-slate-400">Loading flag…</p>;
  const { flag, agent } = detail;
  const merchantFlag = flag.kind === "merchant_silence" || flag.proposed_action === "hold_pool_payout"
    || flag.proposed_action === "lower_merchant_limit";

  async function rerun() {
    live.reset();
    await operatorPost("/v1/stormdesk/run", { candidate_id: flag.candidate_id }).catch(() => undefined);
    load();
    onChanged();
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-3xl font-bold text-white">{KIND_TITLE[flag.kind] ?? flag.kind}</h2>
        <span className={`rounded-full px-3 py-1 text-sm font-semibold ${STATUS_STYLE[flag.status]}`}>{flag.status}</span>
        <span className="rounded-full bg-slate-800 px-3 py-1 text-sm text-slate-300">{flag.severity}</span>
        <RunnerBadge runner={flag.runner} />
      </div>
      <p className="text-lg text-slate-200">
        {flag.subject_name ?? flag.subject_id}: {flag.summary}
      </p>
      {flag.exposure_cents > 0 && <p className="text-slate-400">Exposure: {dollars(flag.exposure_cents)}</p>}
      {agent?.reasoning && (
        <div>
          <button onClick={() => setShowReasoning((v) => !v)} className="text-sm text-sky-300 hover:underline">
            {showReasoning ? "Hide reasoning" : "Show reasoning"}
          </button>
          {showReasoning && <pre className="mt-2 whitespace-pre-wrap font-sans text-base text-slate-300">{agent.reasoning}</pre>}
        </div>
      )}
      <div>
        <div className="mb-1 text-base font-semibold text-slate-200">
          Evidence {flag.citations_valid ? "(every id checked against the database ✓)" : "(citation check failed ✗)"}
        </div>
        <ul className="flex flex-wrap gap-2 font-mono text-xs">
          {flag.evidence_ids.map((e) => (
            <li key={e} className={`rounded px-2 py-1 ${agent?.missing_citations?.includes(e) ? "bg-rose-500/20 text-rose-300" : "bg-slate-800 text-slate-300"}`}>
              {e.length > 20 ? `${e.slice(0, 16)}…` : e}
            </li>
          ))}
          {flag.evidence_ids.length === 0 && <li className="text-slate-500">none</li>}
        </ul>
      </div>
      {live.steps.length > 0 || live.running ? (
        <StepList steps={live.steps} live />
      ) : (
        <StepList steps={agent?.steps ?? []}
          replayLabel={run ? `Replay of run at ${clockTime(run.started_at)}` : undefined} />
      )}
      <button onClick={rerun} className="rounded-lg bg-slate-800 px-4 py-2 text-base text-white hover:bg-slate-700">
        Run StormDesk again
      </button>
      <Decision flag={flag} onDone={() => {
        load();
        onChanged();
      }} />
      {merchantFlag && <PhotonThread merchantId={flag.subject_id} />}
    </div>
  );
}

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

  if (!flags) return <p className="p-8 text-xl text-slate-300">Loading…</p>;
  if (flags.length === 0) {
    return <p className="p-8 text-xl text-slate-400">No StormDesk flags yet. They appear as soon as a detector fires.</p>;
  }
  return (
    <div className="grid gap-6 p-6 lg:grid-cols-[22rem_1fr]">
      <ol className="max-h-[80vh] space-y-2 overflow-y-auto">
        {flags.map((f) => (
          <li key={f.flag_id}>
            <button onClick={() => setSelected(f.flag_id)}
              className={`w-full rounded-xl border p-3 text-left ${
                selected === f.flag_id ? "border-sky-400 bg-slate-800" : "border-slate-800 bg-slate-900 hover:bg-slate-800"}`}>
              <div className="flex justify-between gap-2">
                <span className="font-semibold text-white">{KIND_TITLE[f.kind] ?? f.kind}</span>
                <span className={`rounded-full px-2 text-xs font-semibold ${STATUS_STYLE[f.status]}`}>{f.status}</span>
              </div>
              <div className="truncate text-sm text-slate-400">
                {f.subject_name ?? f.subject_id} · {f.runner === "fake" ? "fake runner" : f.runner ?? ""}
              </div>
            </button>
          </li>
        ))}
      </ol>
      {selected !== null && <FlagView flagId={selected} onChanged={load} />}
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
    <div className="space-y-3 rounded-2xl border border-slate-800 bg-slate-900 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="text-lg font-semibold text-white">StormDesk</h3>
        <RunnerBadge runner={run?.runner} />
        {run && <span className="text-sm text-slate-400">last run {clockTime(run.started_at)} · {run.status}</span>}
        <button disabled={busy} onClick={start}
          className="ml-auto rounded-lg bg-slate-800 px-4 py-2 text-base text-white hover:bg-slate-700 disabled:opacity-50">
          {busy ? "Investigating…" : run ? "Investigate again" : "Investigate"}
        </button>
      </div>
      {live.steps.length > 0 || live.running ? (
        <StepList steps={live.steps} live />
      ) : (
        run?.transcript && (
          <StepList steps={run.transcript.steps} replayLabel={`Replay of run at ${clockTime(run.started_at)}`} />
        )
      )}
    </div>
  );
}
