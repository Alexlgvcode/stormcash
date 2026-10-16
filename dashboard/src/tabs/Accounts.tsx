// Accounts tab (spec §18.2, Capital One add-on): live Nessie balances, the
// Nessie call log, the ledger check and the queued-payout counter.
import { useCallback, useEffect, useRef, useState } from "react";
import { getJSON, type AccountCard, type AccountsSnapshot, type NessieCall } from "../api";
import { useEvents } from "../events";
import { clockTime, dollars, signedDollars } from "../format";

const KIND_STYLE: Record<AccountCard["kind"], string> = {
  checking: "border-sky-500/40",
  escrow: "border-violet-500/40",
  merchant: "border-emerald-500/40",
  pool: "border-amber-500/40",
};

function BalanceCard({ card }: { card: AccountCard }) {
  const value = card.nessie_cents;
  const previous = useRef<number | null>(value);
  const [delta, setDelta] = useState<number | null>(null);

  useEffect(() => {
    if (value !== null && previous.current !== null && value !== previous.current) {
      setDelta(value - previous.current);
      const t = setTimeout(() => setDelta(null), 2500);
      previous.current = value;
      return () => clearTimeout(t);
    }
    previous.current = value;
  }, [value]);

  return (
    <div
      className={`relative rounded-2xl border-2 bg-slate-900 p-5 transition-colors duration-700 ${KIND_STYLE[card.kind]} ${
        delta !== null ? "bg-slate-800" : ""
      }`}
    >
      <div className="text-lg font-medium text-slate-300">{card.label}</div>
      {value !== null ? (
        <div className="mt-1 font-mono text-4xl font-bold tabular-nums text-white">{dollars(value)}</div>
      ) : (
        <div className="mt-1 text-xl font-semibold text-rose-300">
          {card.nessie_account_id ? "Nessie unavailable" : "No Nessie account"}
        </div>
      )}
      {delta !== null && (
        <div
          className={`absolute right-4 top-4 rounded-full px-3 py-1 font-mono text-lg font-bold ${
            delta > 0 ? "bg-emerald-500/20 text-emerald-300" : "bg-rose-500/20 text-rose-300"
          }`}
        >
          {signedDollars(delta)}
        </div>
      )}
      <div className="mt-2 text-sm text-slate-400">
        {value !== null ? "from Nessie transactions" : card.nessie_error ?? ""}
        <span className="float-right">ledger {signedDollars(card.ledger_cents)}</span>
      </div>
    </div>
  );
}

function callLine(c: NessieCall): { kind: string; text: string } {
  const kind = c.path.split("/").filter(Boolean).at(-1) ?? "";
  return { kind: kind.replace(/s$/, ""), text: c.summary ?? c.path };
}

function NessieLog({ calls }: { calls: NessieCall[] }) {
  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
      <h2 className="mb-3 text-xl font-semibold text-white">Nessie call log</h2>
      {calls.length === 0 && <p className="text-slate-400">No Nessie calls yet.</p>}
      <ol className="max-h-[28rem] space-y-1 overflow-y-auto font-mono text-base">
        {calls.map((c) => {
          const { kind, text } = callLine(c);
          const ok = c.status !== null && c.status < 400;
          return (
            <li key={c.call_id} className="flex gap-3 rounded px-2 py-1 even:bg-slate-800/40">
              <span className="shrink-0 text-slate-500">{clockTime(c.created_at)}</span>
              <span className="shrink-0 text-sky-300">
                {c.method} {kind}
              </span>
              <span className="min-w-0 flex-1 truncate text-slate-200">{text}</span>
              <span className={`shrink-0 ${ok ? "text-emerald-400" : "text-rose-400"}`}>
                {c.status === null ? "timeout" : ok ? "completed" : `HTTP ${c.status}`}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

const TOTAL_LABELS: Record<string, string> = {
  checking: "Checking",
  escrow: "Escrow",
  merchant: "Merchants",
  pool: "Guarantee pool",
  fraud_receivable: "Owed by cheaters",
  pool_recoveries: "Pool recoveries",
};

function LedgerPanel({ snap }: { snap: AccountsSnapshot }) {
  const { ledger, nessie, simulated_town: town } = snap;
  return (
    <section className="space-y-4">
      <div className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
        <div className={`text-3xl font-bold ${ledger.balanced ? "text-emerald-400" : "text-rose-400"}`}>
          {ledger.balanced ? "Ledger balanced ✓" : `Ledger unbalanced: ${ledger.unbalanced_txns} transactions`}
        </div>
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-lg">
          {Object.entries(ledger.totals).map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-slate-400">{TOTAL_LABELS[k] ?? k}</dt>
              <dd className="text-right font-mono tabular-nums text-slate-100">{signedDollars(v)}</dd>
            </div>
          ))}
        </dl>
      </div>
      <div className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
        <div className="text-lg text-slate-300">Nessie queued</div>
        <div className={`font-mono text-4xl font-bold ${nessie.queued ? "text-amber-300" : "text-slate-100"}`}>
          {nessie.queued}
        </div>
        <div className="text-sm text-slate-400">
          {nessie.enabled ? "payouts waiting for Nessie; retried every 10 s" : "Nessie is switched off: ledger only"}
        </div>
      </div>
      <div className="rounded-2xl border border-dashed border-slate-700 bg-slate-900/60 p-5">
        <div className="text-lg text-slate-300">{town.label}</div>
        <div className="font-mono text-3xl font-bold text-slate-100">{dollars(town.merchant_cents)}</div>
        <div className="text-sm text-slate-400">
          paid to {town.merchants} simulated merchants · escrow {dollars(town.escrow_cents)}
        </div>
      </div>
    </section>
  );
}

export function AccountsTab() {
  const [snap, setSnap] = useState<AccountsSnapshot | null>(null);
  const [calls, setCalls] = useState<NessieCall[]>([]);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(() => {
    getJSON<AccountsSnapshot>("/v1/accounts")
      .then((s) => {
        setSnap(s);
        setError(null);
      })
      .catch((e) => setError(String(e)));
  }, []);

  // Money moved somewhere: refetch balances, debounced.
  const refresh = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(load, 600);
  }, [load]);

  useEffect(() => {
    load();
    getJSON<NessieCall[]>("/v1/nessie/log?limit=100").then(setCalls).catch(() => undefined);
  }, [load]);

  useEvents(["nessie_call"], (data) => {
    setCalls((prev) => [data as NessieCall, ...prev].slice(0, 200));
    refresh();
  });
  useEvents(["accounts", "payment", "upload"], refresh);

  if (!snap) {
    return <p className="p-8 text-xl text-slate-300">{error ? `Can't reach the server: ${error}` : "Loading…"}</p>;
  }
  return (
    <div className="grid gap-6 p-6 xl:grid-cols-[2fr_1fr]">
      <div className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-2 2xl:grid-cols-3">
          {snap.accounts.map((card) => (
            <BalanceCard key={card.key} card={card} />
          ))}
        </div>
        <NessieLog calls={calls} />
      </div>
      <LedgerPanel snap={snap} />
    </div>
  );
}
