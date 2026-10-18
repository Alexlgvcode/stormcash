// Overview: the command center. The mode and the system's health on one line,
// then where the money is, state by state, for the real phones (Nessie) and the
// simulated town (ledger only) side by side, never summed together. Every
// number is the server's or Nessie's; where a number is derived, it says from what.
import { useState, type ReactNode } from "react";
import { accountAndOwner, callLine, isMoneyMove } from "../accounts";
import type { AccountsSnapshot, CaseSummary, FlagRow, Town } from "../api";
import { ModeChip } from "../components/TopNav";
import { Note, Pill, Source, StatusItem } from "../components/ui";
import { useEvents, useEventsStatus } from "../events";
import { clockTime, dollars } from "../format";
import { useLive, useNow } from "../live";
import { ago, phoneMoney, townMoney, type Tally } from "../overview";
import { bankPill, reconciledLine, type Reconciliation } from "../reconcile";
import { useStatus } from "../status";

const MONEY_EVENTS = ["accounts", "payment", "upload", "nessie_call"];

const n = (v: number | null | undefined) => (v == null ? "—" : v.toLocaleString("en-US"));
const count = (t: Tally, one: string, many = `${one}s`) => `${t.count} ${t.count === 1 ? one : many}`;

/** One status cell: a label, a value, and a line of how it's known. */
function Health({ label, children, sub }: { label: string; children: ReactNode; sub?: ReactNode }) {
  return (
    <div className="min-w-0 border-rule px-4 py-3 [&:not(:first-child)]:border-t sm:[&:not(:first-child)]:border-t-0 sm:[&:not(:first-child)]:border-l">
      <div className="text-eyebrow font-semibold uppercase text-secondary">{label}</div>
      <div className="mt-1 text-ink">{children}</div>
      {sub && <div className="mt-0.5 text-th text-secondary">{sub}</div>}
    </div>
  );
}

function SystemBand({ snap, rec, town }: { snap: AccountsSnapshot | null; rec: Reconciliation | null; town: Town | null }) {
  const link = useEventsStatus();
  const { mode, health } = useStatus();
  const now = useNow();
  const alerts = town?.alerts ?? [];
  return (
    <div className="grid overflow-hidden rounded-[10px] border border-rule bg-surface sm:grid-cols-2 xl:grid-cols-5 [&>*]:sm:border-t [&>*]:sm:[&:nth-child(-n+2)]:border-t-0 xl:[&>*]:border-t-0">
      <Health label="Mode" sub={mode ? <>derived from the {mode.basis}{mode.at ? `, ${ago(mode.at, now)}` : ""}</> : "reading the Nessie log…"}>
        <ModeChip />
      </Health>
      <Health label="Connectivity"
        sub={health ? `Nessie ${health.nessie_enabled ? "on" : "off: ledger only"}${snap?.nessie.queued ? ` · ${snap.nessie.queued} payouts queued` : ""}` : undefined}>
        {link === "live" ? <StatusItem tone="success">Event stream live</StatusItem>
          : link === "connecting" ? <StatusItem tone="warning">Connecting to the stream…</StatusItem>
            : <StatusItem tone="danger">Stream disconnected</StatusItem>}
      </Health>
      <Health label="Ledger" sub={snap ? `as of ${clockTime(snap.as_of)}` : undefined}>
        {!snap ? <span className="text-secondary">…</span> : snap.ledger.balanced
          ? <StatusItem tone="success">Double-entry balanced</StatusItem>
          : <StatusItem tone="danger">{snap.ledger.unbalanced_txns} unbalanced transactions</StatusItem>}
      </Health>
      <Health label="Bank reconciliation" sub={rec ? `checked ${clockTime(rec.checked_at)}` : undefined}>
        {rec ? (() => {
          const line = reconciledLine(rec);
          const tone = line.tone === "ok" ? "success" : line.tone === "off" ? "neutral" : "danger";
          return <StatusItem tone={tone}>{line.text}</StatusItem>;
        })() : <span className="text-secondary">Checking with Nessie…</span>}
      </Health>
      <Health label="Weather and coverage"
        sub={town ? `${town.dark_regions.length} of ${town.regions.length} areas dark (no uploads)` : undefined}>
        {!town ? <span className="text-secondary">…</span> : alerts.length === 0 ? <span className="text-secondary">No active alerts</span> : (
          <span className="flex flex-wrap items-center gap-1.5">
            <StatusItem tone="warning">{alerts.length} {alerts.length === 1 ? "alert" : "alerts"}</StatusItem>
            {[...new Set(alerts.map((a) => a.source))].map((s) => <Source key={s} kind={s === "live" ? "real" : "replayed"} />)}
          </span>
        )}
      </Health>
    </div>
  );
}

interface Stage {
  key: string;
  label: string;
  tone: "teal" | "amber" | "coral" | "none";
  real: ReactNode;
  realSub: ReactNode;
  town: ReactNode;
  townSub: ReactNode;
}

const STAGE_BAR = { teal: "bg-teal", amber: "bg-amber", coral: "bg-coral", none: "bg-rule" };

function Big({ children }: { children: ReactNode }) {
  return <div className="text-[22px] leading-8 font-semibold tabular-nums text-heading">{children}</div>;
}

function MoneyStates({ snap, town, cases }: { snap: AccountsSnapshot; town: Town; cases: CaseSummary[] }) {
  const p = phoneMoney(snap.accounts, town.recent_payments, town.merchants, cases);
  const t = townMoney(snap.simulated_town, town.town_stats, cases);
  const stages: Stage[] = [
    {
      key: "escrow", label: "Escrowed in bank", tone: "none",
      real: p.escrow.cents === null ? "—" : dollars(p.escrow.cents),
      realSub: `${p.escrow.accounts} Nessie escrow ${p.escrow.accounts === 1 ? "account" : "accounts"}`,
      town: dollars(t.escrowCents), townSub: "ledger only",
    },
    {
      key: "allowance", label: "Offline allowance left", tone: "none",
      real: p.allowance === null ? "—" : dollars(p.allowance),
      realSub: "escrow less uploaded-but-unpaid; offline spends not yet uploaded aren't visible",
      town: "—", townSub: "per-wallet; not in the stats",
    },
    {
      key: "accepted", label: "Accepted offline", tone: "amber",
      real: dollars(p.accepted.cents), realSub: `${count(p.accepted, "payment")} uploaded so far`,
      town: n(t.accepted), townSub: t.payments != null ? `of ${n(t.payments)} payments tried` : undefined,
    },
    {
      key: "unsettled", label: "Uploaded, not settled", tone: "amber",
      real: dollars(p.unsettled.cents), realSub: count(p.unsettled, "payment"),
      town: t.accepted != null && t.settled != null ? n(t.accepted - t.settled) : "—", townSub: "accepted − settled",
    },
    {
      key: "settled", label: "Settled to shops", tone: "teal",
      real: dollars(p.settled.cents),
      realSub: p.merchantsPaid !== null ? `${count(p.settled, "payment")} · shops' Nessie: ${dollars(p.merchantsPaid)}` : count(p.settled, "payment"),
      town: dollars(t.merchantCents), townSub: t.settled != null ? `${n(t.settled)} payments · ledger only` : "ledger only",
    },
    {
      key: "exposure", label: "Guarantee exposure", tone: "coral",
      real: dollars(p.exposure.cents), realSub: `across ${count(p.exposure, "case")}`,
      town: dollars(t.exposure.cents), townSub: `across ${count(t.exposure, "case")}`,
    },
    {
      key: "conflicts", label: "Conflicts", tone: "coral",
      real: n(p.exposure.count), realSub: `${p.offlineCatches} caught offline · ${p.refused.count} refused`,
      town: t.attempts != null ? n(t.attempts) : n(t.exposure.count),
      townSub: t.attempts != null
        ? `double-spend attempts: ${n(t.refusedOffline)} refused offline, ${n(t.caughtAtSettlement)} at settlement`
        : "cases",
    },
  ];

  return (
    <section aria-labelledby="money-h">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id="money-h" className="text-section font-semibold text-heading">Where the money is</h2>
        <p className="text-th text-secondary">
          Real phones from Nessie and the server's latest {town.recent_payments.length} payments · simulated town
          (seed {t.seed ?? "—"}) from the ledger and the seeded run. Never added together.
        </p>
      </div>
      {/* Wide: one column per state, a row each for the real phones and the town. */}
      <div className="hidden overflow-hidden rounded-[10px] border border-rule xl:block">
        <table className="w-full table-fixed border-collapse text-left tabular-nums">
          <thead>
            <tr className="bg-surface">
              <th className="w-[8.5rem] border-b border-rule px-4 py-2.5 text-th font-semibold text-secondary">Source</th>
              {stages.map((s) => (
                <th key={s.key} className="border-b border-l border-rule px-3 py-2.5 align-top text-th font-semibold text-secondary">
                  <span className={`mb-2 block h-0.5 w-8 ${STAGE_BAR[s.tone]}`} />
                  {s.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <th className="border-b border-rule px-4 py-3 align-top text-ui font-semibold text-heading">
                Your phones <div className="mt-1"><Source kind="real" /></div>
              </th>
              {stages.map((s) => (
                <td key={s.key} className="border-b border-l border-rule px-3 py-3 align-top">
                  <Big>{s.real}</Big>
                  <div className="mt-0.5 text-th text-secondary">{s.realSub}</div>
                </td>
              ))}
            </tr>
            <tr className="bg-page">
              <th className="px-4 py-3 align-top text-ui font-semibold text-heading">
                Simulated town <div className="mt-1"><Source kind="simulated" /></div>
              </th>
              {stages.map((s) => (
                <td key={s.key} className="border-l border-rule px-3 py-3 align-top">
                  <div className="text-[17px] leading-7 font-semibold tabular-nums text-neutral">{s.town}</div>
                  {s.townSub && <div className="mt-0.5 text-th text-secondary">{s.townSub}</div>}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
      {/* Narrow: one row per state, both sources in it. */}
      <ul className="overflow-hidden rounded-[10px] border border-rule xl:hidden">
        <li className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-3 border-b border-rule bg-surface px-4 py-2 text-th text-secondary sm:grid-cols-[12rem_minmax(0,1fr)_minmax(0,1fr)]">
          <span className="hidden sm:block">State</span>
          <span className="flex items-center gap-1.5">Your phones <Source kind="real" /></span>
          <span className="flex items-center gap-1.5">Town <Source kind="simulated" /></span>
        </li>
        {stages.map((s) => (
          <li key={s.key} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-x-3 gap-y-1 border-b border-rule px-4 py-3 last:border-b-0 sm:grid-cols-[12rem_minmax(0,1fr)_minmax(0,1fr)]">
            <div className="col-span-2 flex items-center gap-2 font-semibold text-heading sm:col-span-1">
              <span className={`h-3 w-0.5 ${STAGE_BAR[s.tone]}`} />
              {s.label}
            </div>
            <div className="min-w-0">
              <div className="text-[19px] leading-7 font-semibold tabular-nums text-heading">{s.real}</div>
              <div className="text-th text-secondary">{s.realSub}</div>
            </div>
            <div className="min-w-0">
              <div className="text-[17px] leading-7 font-semibold tabular-nums text-neutral">{s.town}</div>
              {s.townSub && <div className="text-th text-secondary">{s.townSub}</div>}
            </div>
          </li>
        ))}
      </ul>
      <p className="mt-3 max-w-[110ch] text-th text-secondary">
        Double-spend detection is bounded, not impossible: an isolated shop can be fooled once, up to the wallet's cap,
        and the guarantee pool repays it. Exposure is what the pool stands behind for proven cases.
      </p>
    </section>
  );
}

function BankAccounts({ snap, rec }: { snap: AccountsSnapshot; rec: Reconciliation | null }) {
  const byKey = new Map((rec?.accounts ?? []).map((a) => [a.key, a]));
  return (
    <section className="min-w-0">
      <div className="mb-2 flex items-baseline justify-between gap-3 border-b border-rule pb-2">
        <h2 className="text-section font-semibold text-heading">Bank accounts</h2>
        <a href="#ledger/reconciliation" className="text-th font-semibold text-accent hover:underline">Reconciliation →</a>
      </div>
      <table className="w-full table-fixed border-collapse text-left tabular-nums">
        <thead>
          <tr>
            <th className="border-b border-rule py-2 pr-3 text-th font-semibold text-secondary">Account</th>
            <th className="w-[7.5rem] border-b border-rule py-2 pr-3 text-right text-th font-semibold text-secondary">Nessie</th>
            <th className="hidden w-[9rem] border-b border-rule py-2 text-th font-semibold text-secondary sm:table-cell">Matches ledger</th>
          </tr>
        </thead>
        <tbody>
          {snap.accounts.map((card) => {
            const { account, owner } = accountAndOwner(card);
            const r = byKey.get(card.key);
            const pill = r ? bankPill(r) : null;
            return (
              <tr key={card.key}>
                <td className="border-b border-rule py-2.5 pr-3">
                  <div className="truncate text-heading">{owner}</div>
                  <div className="truncate text-th text-secondary">{account}</div>
                </td>
                <td className="border-b border-rule py-2.5 pr-3 text-right align-top font-semibold text-heading">
                  {card.nessie_cents === null ? <span className="text-secondary" title={card.nessie_error ?? undefined}>—</span> : dollars(card.nessie_cents)}
                  {pill && <div className="sm:hidden"><Pill tone={pill.tone === "ok" ? "success" : pill.tone === "off" ? "neutral" : "danger"}>{pill.tone === "ok" ? "matches" : pill.text}</Pill></div>}
                </td>
                <td className="hidden border-b border-rule py-2.5 align-top sm:table-cell">
                  {pill ? <Pill tone={pill.tone === "ok" ? "success" : pill.tone === "off" ? "neutral" : "danger"}>{pill.tone === "ok" ? "Matches" : pill.text}</Pill>
                    : <span className="text-th text-secondary">checking…</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {snap.simulated_town.merchants > 0 && (
        <p className="mt-2 text-th text-secondary">
          Plus {snap.simulated_town.merchants} simulated shops, ledger only, never sent to Nessie.
        </p>
      )}
    </section>
  );
}

interface Feed {
  id: string;
  at: number;
  tone: "teal" | "amber" | "coral" | "none";
  text: string;
  live: boolean; // arrived on the stream while this page was open
}

const DOT = { teal: "bg-teal", amber: "bg-amber", coral: "bg-coral", none: "bg-secondary" };

function Activity() {
  const { calls } = useStatus();
  const [live, setLive] = useState<Feed[]>([]);
  const push = (f: Feed) => setLive((cur) => [f, ...cur.filter((x) => x.id !== f.id)].slice(0, 30));
  useEvents(["payment"], (d) => {
    const p = d as { tag_hash?: string; merchant_name?: string; amount_cents?: number; status?: string };
    push({ id: `p${p.tag_hash}`, at: Date.now() / 1000, live: true,
      tone: p.status === "settled" ? "teal" : p.status === "refused_evidence" ? "coral" : "amber",
      text: `${p.merchant_name ?? "A shop"} · ${p.amount_cents != null ? dollars(p.amount_cents) : "payment"} · ${(p.status ?? "received").replace("_", " ")}` });
  });
  useEvents(["upload"], (d) => {
    const u = d as { upload_id?: number; accepted?: number; hops?: number; simulated?: boolean };
    push({ id: `u${u.upload_id}`, at: Date.now() / 1000, live: true, tone: "none",
      text: `Upload #${u.upload_id}: ${u.accepted ?? 0} new items${u.simulated ? " (simulated)" : ""}` });
  });
  useEvents(["case_opened"], (d) => {
    const c = d as { case_id: number; rule: string; exposure_cents: number };
    push({ id: `c${c.case_id}`, at: Date.now() / 1000, live: true, tone: "coral",
      text: `Case #${c.case_id} opened: ${c.rule}, exposure ${dollars(c.exposure_cents)}` });
  });
  useEvents(["flag"], (d) => {
    const f = d as { flag_id: number; subject_name?: string | null; status?: string };
    push({ id: `f${f.flag_id}${f.status}`, at: Date.now() / 1000, live: true, tone: "amber",
      text: `StormDesk flag #${f.flag_id}${f.subject_name ? ` on ${f.subject_name}` : ""}: ${f.status ?? "updated"}` });
  });

  const money: Feed[] = (calls ?? []).filter(isMoneyMove).slice(0, 12).map((c) => {
    const { description, cents } = callLine(c);
    const ok = c.status !== null && c.status < 400;
    return { id: `n${c.call_id}`, at: c.created_at, live: false, tone: ok ? "teal" : "coral",
      text: `${description}${cents !== null ? `, ${dollars(cents)}` : ""}${ok ? "" : ` · ${c.status ?? "timeout"}`}` };
  });
  const rows = [...live, ...money].sort((a, b) => b.at - a.at).slice(0, 14);

  return (
    <section className="min-w-0">
      <div className="mb-2 flex items-baseline justify-between gap-3 border-b border-rule pb-2">
        <h2 className="text-section font-semibold text-heading">Activity</h2>
        <span className="text-th text-secondary">Nessie money moves, and live events since this page opened</span>
      </div>
      {calls === null ? <Note>Loading…</Note> : rows.length === 0 ? <Note>Nothing yet.</Note> : (
        <ol>
          {rows.map((r) => (
            <li key={r.id} className="grid grid-cols-[0.5rem_minmax(0,1fr)_auto] items-baseline gap-3 border-b border-rule py-2">
              <span className={`h-2 w-2 translate-y-[-1px] rounded-full ${DOT[r.tone]}`} />
              <span className="min-w-0 break-words text-ink">{r.text}</span>
              <span className="whitespace-nowrap text-th tabular-nums text-secondary">
                {clockTime(Math.floor(r.at))}{r.live && <span className="ml-1 text-success">live</span>}
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function OpenWork({ cases, flags }: { cases: CaseSummary[] | null; flags: FlagRow[] | null }) {
  const open = (flags ?? []).filter((f) => f.status === "open");
  const disagree = open.filter((f) => f.agents_disagree);
  const realCases = (cases ?? []).filter((c) => !c.simulated);
  const latest = realCases[0];
  return (
    <div className="grid gap-px overflow-hidden rounded-[10px] border border-rule bg-rule sm:grid-cols-3">
      <a href="#stormdesk" className="block bg-surface px-4 py-3 hover:bg-raised">
        <div className="text-eyebrow font-semibold uppercase text-secondary">Waiting for a person</div>
        <div className="mt-1 text-[22px] leading-8 font-semibold tabular-nums text-heading">{flags ? open.length : "—"}</div>
        <div className="text-th text-secondary">
          open StormDesk {open.length === 1 ? "proposal" : "proposals"}{disagree.length ? ` · ${disagree.length} where the agents disagree` : ""}
        </div>
      </a>
      <a href="#cases" className="block bg-surface px-4 py-3 hover:bg-raised">
        <div className="text-eyebrow font-semibold uppercase text-secondary">Proven cases, your phones</div>
        <div className="mt-1 text-[22px] leading-8 font-semibold tabular-nums text-heading">{cases ? realCases.length : "—"}</div>
        <div className="truncate text-th text-secondary">
          {latest ? `latest #${latest.case_id}, ${latest.rule}, ${clockTime(latest.created_at)}` : "none yet"}
        </div>
      </a>
      <a href="#cases" className="block bg-surface px-4 py-3 hover:bg-raised">
        <div className="text-eyebrow font-semibold uppercase text-secondary">Proven cases, simulated town</div>
        <div className="mt-1 text-[22px] leading-8 font-semibold tabular-nums text-neutral">
          {cases ? cases.length - realCases.length : "—"}
        </div>
        <div className="text-th text-secondary">signed evidence, seeded run</div>
      </a>
    </div>
  );
}

export function OverviewTab() {
  const accounts = useLive<AccountsSnapshot>("/v1/accounts", MONEY_EVENTS, 600);
  const rec = useLive<Reconciliation>("/v1/accounts/reconcile", MONEY_EVENTS, 1500);
  const town = useLive<Town>("/v1/town", ["town", "upload", "payment", "candidate"]);
  const cases = useLive<CaseSummary[]>("/v1/cases?limit=200", ["case_opened", "town", "upload"]);
  const flags = useLive<FlagRow[]>("/v1/flags?limit=200", ["flag", "approval", "town"]);
  const error = accounts.error ?? town.error;

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-1">
        <div>
          <h1 className="text-[24px] leading-8 font-semibold text-heading sm:text-title">Command center</h1>
          <p className="mt-1 text-secondary">Offline payments, escrow and evidence, live from the server and Capital One Nessie</p>
        </div>
        {accounts.data && <p className="text-th tabular-nums text-secondary">Balances as of {clockTime(accounts.data.as_of)}</p>}
      </header>
      <SystemBand snap={accounts.data} rec={rec.data} town={town.data} />
      {error && !accounts.data && <Note tone="danger">Can't reach the server: {error}</Note>}
      {accounts.data && town.data && cases.data ? (
        <MoneyStates snap={accounts.data} town={town.data} cases={cases.data} />
      ) : !error && <Note>Loading balances, payments and cases…</Note>}
      <OpenWork cases={cases.data} flags={flags.data} />
      <div className="grid gap-8 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        {accounts.data ? <BankAccounts snap={accounts.data} rec={rec.data} /> : <div />}
        <Activity />
      </div>
    </div>
  );
}
