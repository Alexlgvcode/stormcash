// The Accounts tab's wording (spec §18.2, issue #93): which Nessie account a
// balance is and who owns it, and one Nessie call in plain words. Only what the
// server sent, reworded; never a number of our own (§0 rule 3).
// No imports, so `npm test` runs this file directly.

type Kind = "checking" | "escrow" | "merchant" | "pool";

// Spec §11.4's account mapping: each kind of Nessie account and who owns it.
const ACCOUNT: Record<Kind, string> = {
  checking: "Checking",
  escrow: "StormCash escrow",
  merchant: "Merchant account",
  pool: "Guarantee pool",
};
const POOL_OWNER = "StormCash Operator";
const LABEL_SUFFIX: Partial<Record<Kind, string>> = { checking: " Checking", escrow: " Escrow" };

/** "Maya Checking" → Checking, owned by Maya; "Pharmacy" → Merchant account, owned by Pharmacy. */
export function accountAndOwner(card: { label: string; kind: Kind }): { account: string; owner: string } {
  const suffix = LABEL_SUFFIX[card.kind];
  const owner =
    card.kind === "pool"
      ? POOL_OWNER
      : suffix && card.label.endsWith(suffix)
        ? card.label.slice(0, -suffix.length)
        : card.label;
  return { account: ACCOUNT[card.kind], owner };
}

export interface CallLine {
  description: string;
  cents: number | null; // the amount named in the summary; null when it names none
}

/**
 * The server writes each call's summary (nessie.py, registry.py, settlement.py):
 * "Maya escrow → Pharmacy, $12 (withdrawal)", "Open account Guarantee Pool, $1000".
 * The amount moves to its own column; the rest is the description.
 */
export function callLine(c: { method: string; path: string; summary: string | null }): CallLine {
  if (!c.summary) {
    const kind = (c.path.split("/").filter(Boolean).at(-1) ?? "").replace(/s$/, "");
    return { description: `${c.method} ${kind}`, cents: null };
  }
  const m = c.summary.match(/^(.*), \$(\d+)(?:\.(\d\d))?( \((?:withdrawal|deposit)\))?$/);
  if (!m) return { description: c.summary, cents: null };
  return { description: m[1] + (m[4] ?? ""), cents: Number(m[2]) * 100 + Number(m[3] ?? 0) };
}

/** completed, HTTP <code>, or timeout (no answer). */
export function callStatus(status: number | null): { ok: boolean; text: string } {
  if (status === null) return { ok: false, text: "timeout" };
  return status < 400 ? { ok: true, text: "completed" } : { ok: false, text: `HTTP ${status}` };
}
