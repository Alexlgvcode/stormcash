// Accounts tab (spec §18.2, Capital One add-on): live Nessie balances, the
// reconciliation of our ledger with Nessie's own records, the Nessie call log,
// the ledger check and the queued-payout counter. Three views: Balances (what a
// judge sees first), Reconciliation and Nessie log, with the full data.
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { accountAndOwner, callLine, callStatus, isMoneyMove } from "../accounts";
import { getJSON, type AccountCard, type AccountsSnapshot, type NessieCall } from "../api";
import { Button, PageHeader, Pill, Section, StatusItem, Table, Tabs, Td, Th, type Tone as UiTone } from "../components/ui";
import { useEvents } from "../events";
import { clockTime, dollars, signedDollars } from "../format";
import {
  accountsTakeaway,
  bankPill,
  itemsOf,
  openingNote,
  pairsLine,
  reconciledLine,
  simulatedNote,
  unreachable,
  type ReconcileAccount,
  type Reconciliation,
  type Tone,
} from "../reconcile";

const VIEWS = [
  { id: "balances", label: "Balances" },
  { id: "reconciliation", label: "Reconciliation" },
  { id: "log", label: "Nessie log" },
] as const;
export type AccountsView = (typeof VIEWS)[number]["id"];
type View = AccountsView;

// A difference is red, like an outage; ledger-only accounts are neutral.
const TONE: Record<Tone, UiTone> = { ok: "success", diff: "danger", error: "danger", off: "neutral" };

const LATEST_CALLS = 8;

interface ReconcileState {
  result: Reconciliation | null;
  lastOk: number | null;
  error: string | null;
  busy: boolean;
  run: () => void;
}

// GET /v1/accounts/reconcile, re-run (debounced) when money moves; one check at a time.
function useReconcile(): ReconcileState {
  const [result, setResult] = useState<Reconciliation | null>(null);
  const [lastOk, setLastOk] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const again = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const run = useCallback(function check() {
    if (inFlight.current) {
      again.current = true; // one more check once this one answers
      return;
    }
    inFlight.current = true;
    setBusy(true);
    getJSON<Reconciliation>("/v1/accounts/reconcile")
      .then((r) => {
        setResult(r);
        setError(null);
        if (r.ok) setLastOk(r.checked_at);
      })
      .catch((e) => setError(String(e)))
      .finally(() => {
        inFlight.current = false;
        setBusy(false);
        if (again.current) {
          again.current = false;
          check();
        }
      });
  }, []);

  useEffect(run, [run]);
  // Payouts and Nessie calls change what reconciles: check again, debounced.
  useEvents(["accounts", "payment", "upload", "nessie_call"], () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(run, 1500);
  });

  return { result, lastOk, error, busy, run };
}

/** The reconcile part of a status line: the count, or why there is none. */
function ReconcileStatus({ rec }: { rec: ReconcileState }) {
  if (rec.error) {
    return (
      <StatusItem tone="danger">
        Can't reach the server: {rec.error}
        {rec.lastOk !== null && ` Last successful check: ${clockTime(rec.lastOk)}.`}
      </StatusItem>
    );
  }
  if (!rec.result) return <span className="text-secondary">Checking with Nessie…</span>;
  const line = reconciledLine(rec.result);
  return <StatusItem tone={TONE[line.tone]}>{line.text}</StatusItem>;
}

function StatusLine({ children }: { children: ReactNode }) {
  return <div className="mb-6 flex flex-wrap items-center gap-x-6 gap-y-2">{children}</div>;
}

function BalanceRow({ card, rec }: { card: AccountCard; rec: ReconcileAccount | undefined }) {
  const value = card.nessie_cents;
  const previous = useRef<number | null>(value);
  const [delta, setDelta] = useState<number | null>(null);

  // Animate a change (spec §18.2): the difference shows beside the balance for a moment.
  useEffect(() => {
    if (value !== null && previous.current !== null && value !== previous.current) {
      setDelta(value - previous.current);
      const t = setTimeout(() => setDelta(null), 2500);
      previous.current = value;
      return () => clearTimeout(t);
    }
    previous.current = value;
  }, [value]);

  const { account, owner } = accountAndOwner(card);
  const pill = rec ? bankPill(rec) : null;
  // An account row in the bank style: who and which account, what the bank says, the balance big on the right.
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b border-rule py-4">
      <div className="min-w-0">
        <div className="text-[17px] font-semibold text-heading">{owner} · {account}</div>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-th text-secondary">
          {pill ? (
            <Pill tone={TONE[pill.tone]} title={rec?.error ?? undefined}>
              {pill.tone === "ok" ? "Matches the bank" : pill.text}
            </Pill>
          ) : (
            <span>Checking with the bank…</span>
          )}
          {value !== null && <span>from Nessie transactions</span>}
        </div>
      </div>
      <div className="flex items-center gap-3">
        {delta !== null && <Pill tone={delta > 0 ? "success" : "danger"}>{signedDollars(delta)}</Pill>}
        {value !== null ? (
          <span className="text-[22px] leading-8 font-semibold tabular-nums text-heading sm:text-[26px] sm:leading-9">{dollars(value)}</span>
        ) : (
          <span className="text-secondary" title={card.nessie_error ?? undefined}>
            {card.nessie_account_id ? "Nessie unavailable" : "No Nessie account"}
          </span>
        )}
      </div>
    </li>
  );
}

/** "Show setup calls": opening accounts and creating customers, hidden by default. */
function SetupToggle({ on, set, hidden }: { on: boolean; set: (v: boolean) => void; hidden: number }) {
  return (
    <label className="flex items-center gap-2 text-th text-ink">
      <input type="checkbox" checked={on} onChange={(e) => set(e.target.checked)} className="h-4 w-4 accent-accent" />
      Show setup calls{!on && hidden > 0 ? ` (${hidden} hidden)` : ""}
    </label>
  );
}

/** Recent money movements as bank-statement rows: what happened, when and its status, the amount on the right. */
function ActivityList({ calls }: { calls: NessieCall[] }) {
  if (calls.length === 0) return <p className="py-3 text-secondary">No Nessie calls yet.</p>;
  return (
    <ul>
      {calls.map((c) => {
        const { description, cents } = callLine(c);
        const status = callStatus(c.status);
        return (
          <li key={c.call_id} className="flex items-center justify-between gap-6 border-b border-rule py-3.5">
            <div className="min-w-0">
              <div className="break-words text-ink">{description}</div>
              <div className="mt-1 flex items-center gap-2 text-th text-secondary">
                <span className="tabular-nums">{clockTime(c.created_at)}</span>
                <Pill tone={status.ok ? "success" : "danger"}>{status.text}</Pill>
              </div>
            </div>
            {cents !== null && <span className="whitespace-nowrap text-[18px] font-semibold tabular-nums text-heading">{dollars(cents)}</span>}
          </li>
        );
      })}
    </ul>
  );
}

function CallTable({ calls, header = false }: { calls: NessieCall[]; header?: boolean }) {
  if (calls.length === 0) return <p className="py-3 text-secondary">No Nessie calls yet.</p>;
  return (
    <Table>
      {header && (
        <thead>
          <tr>
            <Th className="w-32">Time</Th>
            <Th>Description</Th>
            <Th num>Amount</Th>
            <Th className="w-32">Status</Th>
          </tr>
        </thead>
      )}
      <tbody>
        {calls.map((c) => {
          const { description, cents } = callLine(c);
          const status = callStatus(c.status);
          return (
            <tr key={c.call_id}>
              <Td className="w-32 whitespace-nowrap tabular-nums text-secondary">{clockTime(c.created_at)}</Td>
              <Td className="break-words">{description}</Td>
              <Td num className="font-medium text-heading">
                {cents !== null ? dollars(cents) : ""}
              </Td>
              <Td className="w-32">
                <Pill tone={status.ok ? "success" : "danger"}>{status.text}</Pill>
              </Td>
            </tr>
          );
        })}
      </tbody>
    </Table>
  );
}

function Balances({ snap, rec, calls, setup, setSetup }: {
  snap: AccountsSnapshot;
  rec: ReconcileState;
  calls: NessieCall[];
  setup: boolean;
  setSetup: (v: boolean) => void;
}) {
  const shown = setup ? calls : calls.filter(isMoneyMove);
  const byKey = new Map((rec.result?.accounts ?? []).map((a) => [a.key, a]));
  const { ledger, nessie, simulated_town: town } = snap;
  return (
    <>
      <StatusLine>
        {ledger.balanced ? (
          <StatusItem tone="success">Ledger balanced</StatusItem>
        ) : (
          <StatusItem tone="danger">Ledger unbalanced: {ledger.unbalanced_txns} transactions</StatusItem>
        )}
        <ReconcileStatus rec={rec} />
        {nessie.queued > 0 && <StatusItem tone="warning">Payouts waiting for Nessie: {nessie.queued}</StatusItem>}
        {rec.result && <span className="text-secondary">Checked {clockTime(rec.result.checked_at)}</span>}
      </StatusLine>
      <ul className="border-t border-rule">
        {snap.accounts.map((card) => (
          <BalanceRow key={card.key} card={card} rec={byKey.get(card.key)} />
        ))}
      </ul>
      {town.merchants > 0 && (
        <p className="mt-4 text-secondary">Simulated town: {town.merchants} shops, ledger only, never sent to Nessie</p>
      )}
      <div className="mt-10">
        <Section title="Recent Nessie activity" right={<SetupToggle on={setup} set={setSetup} hidden={calls.length - shown.length} />}>
          <ActivityList calls={shown.slice(0, LATEST_CALLS)} />
        </Section>
      </div>
    </>
  );
}

function ReconcileDetails({ a, checkedAt }: { a: ReconcileAccount; checkedAt: number }) {
  return (
    <div className="space-y-2 text-secondary">
      {a.error && <p className={a.status === "error" ? "text-danger" : undefined}>{a.error}</p>}
      {(a.by_kind ?? []).map((k) => {
        const { shown, more } = itemsOf(a, k.kind);
        return (
          <div key={k.kind}>
            <div className="text-ink">
              <span className="font-medium">{k.label}</span>{" "}
              <span className="tabular-nums">{signedDollars(k.cents)}</span>
              {k.count > 1 && <span className="text-secondary"> · {k.count} transactions</span>}
            </div>
            <ul className="ml-5 list-disc">
              {shown.map((i, n) => (
                <li key={`${i.txn_id}-${n}`} className="break-words">
                  {i.text}
                </li>
              ))}
              {more > 0 && <li>and {more} more</li>}
            </ul>
          </div>
        );
      })}
      {a.simulated && <p>{simulatedNote(a.simulated)}</p>}
      {a.opening && <p>{openingNote(a.opening)}</p>}
      {a.fetched_at !== undefined && a.fetched_at < checkedAt - 1 && (
        <p>Nessie records as read at {clockTime(a.fetched_at)} (cached ≤ 10 s)</p>
      )}
    </div>
  );
}

const hasDetails = (a: ReconcileAccount) =>
  !!(a.error || a.by_kind?.length || a.simulated || a.opening || a.fetched_at !== undefined);

const TOTAL_LABELS: Record<string, string> = {
  checking: "Checking",
  escrow: "Escrow",
  merchant: "Merchants",
  pool: "Guarantee pool",
  fraud_receivable: "Owed by cheaters",
  pool_recoveries: "Pool recoveries",
};

function ReconciliationView({ snap, rec }: { snap: AccountsSnapshot; rec: ReconcileState }) {
  const r = rec.result;
  const down = r ? unreachable({ ...r, last_ok_at: r.last_ok_at ?? rec.lastOk }, clockTime) : null;
  const pairs = r && r.nessie.enabled ? pairsLine(r.pairs) : null;
  const { ledger } = snap;
  return (
    <>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <p className="max-w-3xl text-secondary">
          Our double-entry ledger against Nessie's own records (opening balance + completed deposits − completed
          withdrawals), matched by the StormCash transaction id written into every Nessie description.
        </p>
        <Button primary onClick={rec.run} disabled={rec.busy}>
          {rec.busy ? "Checking…" : "Re-check"}
        </Button>
      </div>
      <StatusLine>
        <ReconcileStatus rec={rec} />
        {r && <span className="text-secondary">Checked {clockTime(r.checked_at)}</span>}
      </StatusLine>
      {down && <p className="-mt-3 mb-6 text-danger">{down}</p>}
      {r && (
        <>
          <Table>
            <thead>
              <tr>
                <Th>Account</Th>
                <Th className="max-sm:hidden">Owner</Th>
                <Th num>Ledger expects</Th>
                <Th num>Nessie has</Th>
                <Th>Bank</Th>
              </tr>
            </thead>
            {r.accounts.map((a) => {
              const { account, owner } = accountAndOwner(a);
              const read = a.status === "reconciled" || a.status === "difference";
              const pill = bankPill(a);
              const details = hasDetails(a);
              return (
                <tbody key={a.key}>
                  <tr>
                    <Td rule={!details} className="font-medium text-heading">
                      {account}
                      <span className="block font-normal text-secondary sm:hidden">{owner}</span>
                    </Td>
                    <Td rule={!details} className="max-sm:hidden">{owner}</Td>
                    <Td rule={!details} num>
                      {read ? dollars(a.expected_cents!) : <span className="text-secondary">—</span>}
                    </Td>
                    <Td rule={!details} num>
                      {read ? dollars(a.nessie_cents!) : <span className="text-secondary">—</span>}
                    </Td>
                    <Td rule={!details}>
                      <Pill tone={TONE[pill.tone]}>{pill.text}</Pill>
                    </Td>
                  </tr>
                  {details && (
                    <tr>
                      <Td colSpan={5} className="pt-0">
                        <ReconcileDetails a={a} checkedAt={r.checked_at} />
                      </Td>
                    </tr>
                  )}
                </tbody>
              );
            })}
          </Table>
          {pairs && (
            <div className="mt-6">
              <StatusItem tone={TONE[pairs.tone]}>{pairs.text}</StatusItem>
              {r.pairs.problems.length > 0 && (
                <ul className="mt-2 ml-6 list-disc text-secondary">
                  {r.pairs.problems.slice(0, 5).map((p) => (
                    <li key={p.txn_id} className="break-words">
                      {p.text}
                    </li>
                  ))}
                  {r.pairs.problems_total > 5 && <li>and {r.pairs.problems_total - 5} more</li>}
                </ul>
              )}
            </div>
          )}
          <p className="mt-4 text-secondary">
            {r.simulated_town.label}: {dollars(r.simulated_town.merchant_cents)} at {r.simulated_town.merchants}{" "}
            simulated shops, not a difference.
          </p>
        </>
      )}
      <div className="mt-10">
        <Section title="Ledger">
          <StatusLine>
            {ledger.balanced ? (
              <StatusItem tone="success">Ledger balanced</StatusItem>
            ) : (
              <StatusItem tone="danger">Ledger unbalanced: {ledger.unbalanced_txns} transactions</StatusItem>
            )}
          </StatusLine>
          <Table>
            <thead>
              <tr>
                <Th>Account type</Th>
                <Th num>Total</Th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(ledger.totals).map(([k, v]) => (
                <tr key={k}>
                  <Td>{TOTAL_LABELS[k] ?? k}</Td>
                  <Td num className="font-medium text-heading">
                    {signedDollars(v)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Section>
      </div>
    </>
  );
}

function NessieLog({ snap, calls, setup, setSetup }: {
  snap: AccountsSnapshot;
  calls: NessieCall[];
  setup: boolean;
  setSetup: (v: boolean) => void;
}) {
  const { nessie } = snap;
  const shown = setup ? calls : calls.filter(isMoneyMove);
  return (
    <>
      <StatusLine>
        {nessie.enabled ? (
          <StatusItem tone={nessie.queued ? "warning" : "success"}>Payouts waiting for Nessie: {nessie.queued}</StatusItem>
        ) : (
          <StatusItem tone="neutral">Nessie is switched off: ledger only</StatusItem>
        )}
        {nessie.enabled && <span className="text-secondary">retried every 10 seconds</span>}
        <span className="ml-auto"><SetupToggle on={setup} set={setSetup} hidden={calls.length - shown.length} /></span>
      </StatusLine>
      <CallTable calls={shown} header />
    </>
  );
}

/** Inside the Ledger workspace, `view` picks the view and the workspace draws the header. */
export function AccountsTab({ view: forced }: { view?: View } = {}) {
  const [own, setView] = useState<View>("balances");
  const view = forced ?? own;
  const [setup, setSetup] = useState(false); // account setup calls (open account, create customer) hidden by default
  const [snap, setSnap] = useState<AccountsSnapshot | null>(null);
  const [calls, setCalls] = useState<NessieCall[]>([]);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const rec = useReconcile();

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

  return (
    <div>
      {forced ? (
        rec.result && <p className="mb-6 max-w-[90ch] text-ink">{accountsTakeaway(rec.result)}</p>
      ) : (
        <PageHeader title="Accounts" subtitle="Balances from Capital One Nessie transactions"
          takeaway={rec.result ? accountsTakeaway(rec.result) : undefined}>
          <Tabs tabs={VIEWS} value={view} onChange={setView} />
        </PageHeader>
      )}
      {!snap ? (
        <p className={error ? "text-danger" : "text-secondary"}>{error ? `Can't reach the server: ${error}` : "Loading…"}</p>
      ) : view === "balances" ? (
        <Balances snap={snap} rec={rec} calls={calls} setup={setup} setSetup={setSetup} />
      ) : view === "reconciliation" ? (
        <ReconciliationView snap={snap} rec={rec} />
      ) : (
        <NessieLog snap={snap} calls={calls} setup={setup} setSetup={setSetup} />
      )}
    </div>
  );
}
