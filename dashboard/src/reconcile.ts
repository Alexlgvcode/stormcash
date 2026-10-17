// The reconciliation panel's data (spec §11.4a, §18.2): GET /v1/accounts/reconcile
// compares our double-entry ledger with Capital One Nessie's own records. These
// helpers only word what the server computed; an account Nessie couldn't be read
// for shows the error, never a number (§0 rule 3).
// No imports, so `npm test` runs this file directly.

export type ItemKind =
  | "opening"
  | "queued"
  | "half_pair"
  | "in_flight"
  | "pending_in_nessie"
  | "ledger_only"
  | "held"
  | "not_in_ledger"
  | "unlinked"
  | "unexplained";

export interface ReconcileItem {
  kind: ItemKind;
  cents: number; // this item's share of the difference (Nessie − ledger)
  txn_id: string | null;
  text: string;
}

export interface ReconcileKind {
  kind: ItemKind;
  label: string;
  count: number;
  cents: number;
}

export interface Opening {
  cents: number;
  source: "call_log" | "rule" | "nessie";
  call_id: number | null;
  at: number | null;
  nessie_cents: number;
}

export interface ReconcileAccount {
  key: string;
  label: string;
  kind: "checking" | "escrow" | "merchant" | "pool";
  nessie_account_id: string | null;
  status: "reconciled" | "difference" | "error" | "no_nessie_account";
  error: string | null;
  fetched_at?: number;
  opening?: Opening;
  ledger_cents?: number;
  simulated?: { cents: number; txns: number; label: string } | null;
  expected_cents?: number;
  nessie_cents?: number;
  difference_cents?: number;
  records?: { deposits: number; withdrawals: number; linked: number; unlinked: number; not_completed: number };
  by_kind?: ReconcileKind[];
  items?: ReconcileItem[];
  items_total?: number;
}

export interface PairProblem {
  txn_id: string;
  kind: string;
  text: string;
}

export interface Reconciliation {
  checked_at: number;
  ok: boolean;
  last_ok_at: number | null;
  nessie: { enabled: boolean; error: string | null };
  accounts: ReconcileAccount[];
  pairs: { checked: number; complete: number; problems: PairProblem[]; problems_total: number };
  simulated_town: { label: string; merchants: number; merchant_cents: number };
}

export function usd(cents: number): string {
  const sign = cents < 0 ? "−" : "";
  const abs = Math.abs(cents);
  return `${sign}$${Math.floor(abs / 100).toLocaleString("en-US")}.${String(abs % 100).padStart(2, "0")}`;
}

export function signedUsd(cents: number): string {
  return cents > 0 ? `+${usd(cents)}` : usd(cents);
}

export type Tone = "ok" | "diff" | "error" | "off";

/** What the bank says about one account: Matches, the difference and its reasons, or why it has no number. */
export function bankPill(a: ReconcileAccount): { tone: Tone; text: string } {
  switch (a.status) {
    case "reconciled":
      return { tone: "ok", text: "Matches" };
    case "difference": {
      const why = (a.by_kind ?? []).map((k) => k.label).join("; ") || "Unexplained";
      return { tone: "diff", text: `${signedUsd(a.difference_cents ?? 0)} · ${why}` };
    }
    case "error":
      return { tone: "error", text: "Nessie unreachable" };
    default:
      return { tone: "off", text: "Ledger only" };
  }
}

/** "Reconciled with Nessie, 4 of 5 accounts · 1 with a difference", counted only over accounts that were read. */
export function reconciledLine(r: Reconciliation): { tone: Tone; text: string } {
  if (!r.nessie.enabled) return { tone: "off", text: "Nessie is switched off: every account is ledger only" };
  const read = r.accounts.filter((a) => a.status === "reconciled" || a.status === "difference");
  const ok = read.filter((a) => a.status === "reconciled").length;
  const errors = r.accounts.filter((a) => a.status === "error").length;
  if (read.length === 0 && errors) return { tone: "error", text: "Nessie unreachable: nothing could be checked" };
  const parts = [`Reconciled with Nessie, ${ok} of ${read.length} ${read.length === 1 ? "account" : "accounts"}`];
  if (read.length - ok) parts.push(`${read.length - ok} with a difference`);
  if (errors) parts.push(`${errors} unreadable`);
  return { tone: errors ? "error" : ok === read.length && read.length > 0 ? "ok" : "diff", text: parts.join(" · ") };
}

/** How the opening balance is represented on each side. */
export function openingNote(o: Opening): string {
  const nessie = `Nessie keeps ${usd(o.nessie_cents)} as the account's fixed opening balance`;
  if (o.source === "nessie") return `${nessie}; we have no record of the opening, so it is taken from Nessie.`;
  const ours =
    o.source === "call_log"
      ? `our call log #${o.call_id} opened it at ${usd(o.cents)}`
      : `StormCash opens this kind of account at ${usd(o.cents)}`;
  return `${nessie}; ${ours}${o.cents === o.nessie_cents ? " ✓" : ""}. The ledger books movements only.`;
}

export function simulatedNote(s: { cents: number; txns: number; label: string }): string {
  return `${signedUsd(s.cents)} in ${s.txns} simulated ${s.txns === 1 ? "transaction" : "transactions"}: ${s.label}`;
}

export function pairsLine(p: Reconciliation["pairs"]): { tone: Tone; text: string } {
  if (p.checked === 0) return { tone: "off", text: "No SC pairs in Nessie on these accounts yet" };
  const all = p.complete === p.checked;
  return {
    tone: all ? "ok" : "diff",
    text: `${p.complete} of ${p.checked} SC pairs complete (one withdrawal + one deposit) and matching the ledger${
      all ? " ✓" : ""
    }`,
  };
}

/** Plain words when Nessie can't be read; `clock` formats Unix seconds. */
export function unreachable(r: Reconciliation, clock: (t: number) => string): string | null {
  if (!r.nessie.enabled || r.ok) return null;
  const last = r.last_ok_at ? `Last successful check: ${clock(r.last_ok_at)}.` : "No successful check since the server started.";
  return `Capital One Nessie can't be read right now (${r.nessie.error ?? "error"}). ${last}`;
}

/** The first few items of one kind, and how many more the server counted. */
export function itemsOf(a: ReconcileAccount, kind: ItemKind, limit = 3): { shown: ReconcileItem[]; more: number } {
  const all = (a.items ?? []).filter((i) => i.kind === kind);
  const total = a.by_kind?.find((k) => k.kind === kind)?.count ?? all.length;
  return { shown: all.slice(0, limit), more: Math.max(0, total - Math.min(limit, all.length)) };
}
