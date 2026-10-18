// The Overview's numbers (the command center): the mode, and where the money
// is, for the real phones and for the simulated town, kept apart. Every number
// is a sum or count of what the server sent; nothing here invents one (§0 rule 3).
// No imports, so `npm test` runs this file directly.

interface Call {
  summary: string | null;
  created_at: number;
}

export type Mode = "storm" | "normal" | "unknown";

/**
 * Storm Mode isn't reported by any GET, but every change of mode moves money in
 * Nessie, and the server writes what it was into the call's summary
 * (registry.py): "Storm Mode top-up, …" raises the cap, "Refund on close, …"
 * returns it. The newer of the two says the mode. Calls are newest first.
 */
export function modeFromCalls(calls: Call[]): { mode: Mode; at: number | null; basis: string } {
  const up = calls.find((c) => c.summary?.startsWith("Storm Mode top-up"));
  const close = calls.find((c) => c.summary?.startsWith("Refund on close"));
  if (up && (!close || up.created_at >= close.created_at)) {
    return { mode: "storm", at: up.created_at, basis: "latest Nessie top-up into escrow" };
  }
  if (close) return { mode: "normal", at: close.created_at, basis: "latest Nessie refund on close" };
  if (calls.some((c) => c.summary?.startsWith("Lock escrow"))) {
    return { mode: "normal", at: null, basis: "escrow locked at the base cap, no top-up in the log" };
  }
  return { mode: "unknown", at: null, basis: "no escrow moves in the Nessie log yet" };
}

interface Card {
  kind: "checking" | "escrow" | "merchant" | "pool";
  nessie_cents: number | null;
  ledger_cents: number;
}

interface Payment {
  tag_hash: string;
  merchant_id: string;
  status: string;
  amount_cents: number;
}

interface Shop {
  merchant_id: string;
  simulated: boolean;
}

interface CaseRow {
  simulated?: boolean;
  exposure_cents: number;
  detected_where: "offline" | "server";
}

export interface Tally {
  cents: number;
  count: number;
}

const tally = (rows: { amount_cents: number }[]): Tally => ({
  cents: rows.reduce((s, r) => s + r.amount_cents, 0),
  count: rows.length,
});

// payments.status (schema.sql): which ones a shop accepted offline, and how far each got.
const ACCEPTED = new Set(["pending", "settled", "held", "denied_knowing"]);
const UNSETTLED = new Set(["pending", "held"]);

export interface PhoneMoney {
  escrow: { cents: number | null; accounts: number }; // in Nessie, now
  allowance: number | null; // escrow minus what's uploaded but not yet paid from it
  accepted: Tally; // accepted offline and uploaded since
  unsettled: Tally;
  settled: Tally;
  refused: Tally; // refused offline, kept as evidence
  exposure: Tally; // cases' exposure
  offlineCatches: number;
  merchantsPaid: number | null; // merchant accounts in Nessie, to check `settled` against
}

/** The real phones' money, from Nessie balances and the server's payments. */
export function phoneMoney(cards: Card[], payments: Payment[], shops: Shop[], cases: CaseRow[]): PhoneMoney {
  const realShop = new Set(shops.filter((s) => !s.simulated).map((s) => s.merchant_id));
  const mine = payments.filter((p) => realShop.has(p.merchant_id));
  const escrows = cards.filter((c) => c.kind === "escrow");
  const read = escrows.filter((c) => c.nessie_cents !== null);
  const escrowCents = read.length ? read.reduce((s, c) => s + c.nessie_cents!, 0) : null;
  const unsettled = tally(mine.filter((p) => UNSETTLED.has(p.status)));
  const merchants = cards.filter((c) => c.kind === "merchant" && c.nessie_cents !== null);
  const realCases = cases.filter((c) => !c.simulated);
  return {
    escrow: { cents: escrowCents, accounts: escrows.length },
    allowance: escrowCents === null ? null : Math.max(0, escrowCents - unsettled.cents),
    accepted: tally(mine.filter((p) => ACCEPTED.has(p.status))),
    unsettled,
    settled: tally(mine.filter((p) => p.status === "settled")),
    refused: tally(mine.filter((p) => p.status === "refused_evidence")),
    exposure: { cents: realCases.reduce((s, c) => s + c.exposure_cents, 0), count: realCases.length },
    offlineCatches: realCases.filter((c) => c.detected_where === "offline").length,
    merchantsPaid: merchants.length ? merchants.reduce((s, c) => s + c.nessie_cents!, 0) : null,
  };
}

interface TownSummary {
  payments?: number;
  accepted?: number;
  settled?: number;
  refused?: Record<string, number>;
  shops?: number;
  residents?: number;
  hours?: number;
}

interface TownStatsLike {
  seed: number;
  summary?: TownSummary;
  double_spends: { attempts: number; refused_offline?: number; accepted_offline?: number; caught_at_settlement?: number;
    not_caught_by_end?: number };
  mean_loss_per_cheater_cents: number | null;
  cheaters?: number;
}

export interface TownMoney {
  seed: number | null;
  escrowCents: number; // ledger only
  merchantCents: number; // paid to simulated shops, ledger only
  payments: number | null;
  accepted: number | null;
  settled: number | null;
  refused: number | null;
  attempts: number | null;
  refusedOffline: number | null;
  caughtAtSettlement: number | null;
  notCaught: number | null;
  exposure: Tally; // cases' exposure
}

/** The simulated town's money: ledger totals and the seeded run's own counts. */
export function townMoney(
  sim: { escrow_cents: number; merchant_cents: number },
  stats: TownStatsLike | null,
  cases: CaseRow[],
): TownMoney {
  const s = stats?.summary;
  const ds = stats?.double_spends;
  const simCases = cases.filter((c) => c.simulated);
  return {
    seed: stats?.seed ?? null,
    escrowCents: sim.escrow_cents,
    merchantCents: sim.merchant_cents,
    payments: s?.payments ?? null,
    accepted: s?.accepted ?? null,
    settled: s?.settled ?? null,
    refused: s?.refused ? Object.values(s.refused).reduce((a, b) => a + b, 0) : null,
    attempts: ds?.attempts ?? null,
    refusedOffline: ds?.refused_offline ?? null,
    caughtAtSettlement: ds?.caught_at_settlement ?? null,
    notCaught: ds?.not_caught_by_end ?? null,
    exposure: { cents: simCases.reduce((sum, c) => sum + c.exposure_cents, 0), count: simCases.length },
  };
}

/** "3 min ago", "2 h ago", for how old the latest thing is. */
export function ago(unixSeconds: number, now: number): string {
  const s = Math.max(0, now - unixSeconds);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}
