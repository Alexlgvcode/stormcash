// The Cases tab in plain words (issue #93): each case titled as what happened,
// the conflict between the two signed payments as a sentence, the tab's
// takeaway, and the browser's checks without our object names. Only the
// server's fields, reworded; never a number of our own (§0 rule 3).
// No imports, so `npm test` runs this file directly.

export interface CasePayment {
  counter: number;
  amount_cents: number;
  status: string | null;
  merchant: string | null;
  simulated: boolean | null;
}

export interface CaseRow {
  case_id: number;
  rule: string;
  detected_where: "offline" | "server";
  exposure_cents: number;
  simulated?: boolean;
  merchant?: string | null;
  payment_a?: CasePayment | null;
  payment_b?: CasePayment | null;
}

type Fields = Record<string, string | number | string[]>;

function usd(cents: number): string {
  const abs = Math.abs(cents);
  return `${cents < 0 ? "−" : ""}$${Math.floor(abs / 100).toLocaleString("en-US")}.${String(abs % 100).padStart(2, "0")}`;
}

// What a double spend did to the wallet, per rule.
const HOW: Record<string, string> = {
  SAME_COUNTER: "the same payment number was used twice",
  BROKEN_LINK: "the wallet was rolled back",
  TOTAL_BACKWARDS: "a payment number was skipped",
};

/** "Swannanoa Bakery refused $8.61: the wallet was rolled back". */
export function caseTitle(c: CaseRow): string {
  const pays = [c.payment_a, c.payment_b].filter((p): p is CasePayment => !!p);
  const refused = [c.payment_b, c.payment_a].find((p) => p?.status === "refused_evidence"); // the later payment first
  const last = c.payment_b ?? c.payment_a;
  const amount = last ? usd(last.amount_cents) : usd(c.exposure_cents);
  if (HOW[c.rule]) {
    if (refused) return `${refused.merchant ?? "A shop"} refused ${usd(refused.amount_cents)}: ${HOW[c.rule]}`;
    const shops = [...new Set(pays.map((p) => p.merchant).filter(Boolean))];
    return `${amount} spent twice${shops.length ? ` at ${shops.join(" and ")}` : ""}: ${HOW[c.rule]}`;
  }
  if (c.rule === "MERCHANT_KNEW") {
    return `${c.merchant ?? last?.merchant ?? "A shop"} accepted ${amount} it knew was already spent`;
  }
  if (c.rule === "OVER_CAP") return `${c.payment_a?.merchant ?? "A shop"} was paid ${amount} over the wallet's limit`;
  if (c.rule === "LOG_TAMPER") return `${c.merchant ? `${c.merchant}'s` : "A device's"} signed log was altered`;
  return `Case #${c.case_id}`;
}

/** What the two signed payments disagree on, in one sentence; null when the table can't show it. */
export function conflictSentence(rule: string, a: Fields, b?: Fields | null): string | null {
  if (!b) {
    return `The running total reaches ${usd(Number(a.cum_cents))}, more than any limit this wallet was ever given.`;
  }
  const [lo, hi] = Number(a.counter) <= Number(b.counter) ? [a, b] : [b, a];
  if (rule === "SAME_COUNTER") {
    return `Both payments use payment number ${a.counter}: an honest wallet uses each number once.`;
  }
  if (rule === "BROKEN_LINK") {
    return `Payment ${hi.counter} should continue from payment ${lo.counter}, but points to a different payment.`;
  }
  if (rule === "TOTAL_BACKWARDS") {
    const before = Number(hi.cum_cents) - Number(hi.amount_cents);
    return `Payment ${hi.counter} says ${usd(before)} was spent before it, but payment ${lo.counter} had already brought the total to ${usd(Number(lo.cum_cents))}.`;
  }
  return null;
}

/** "1 proven case from your phones, 58 from the simulated town." */
export function casesTakeaway(rows: Pick<CaseRow, "simulated">[]): string {
  const sim = rows.filter((r) => r.simulated).length;
  const real = rows.length - sim;
  const phones = real === 0 ? "No proven cases from your phones yet" : `${real} proven ${real === 1 ? "case" : "cases"} from your phones`;
  return `${phones}, ${sim} from the simulated town.`;
}

/**
 * The browser's checks without our object names: the certificate, then payment
 * A's two checks, then payment B's, in the order runChecks makes them.
 */
export function plainChecks<T extends { label: string }>(checks: T[]): T[] {
  let tags = 0;
  return checks.map((c) => {
    let label = c.label
      .replace(/the signed text matches the fields shown/, "the signed text matches what's shown")
      .replace(/signature is valid for the StormCash server key (\S+)/, "signed by the StormCash server (key $1)")
      .replace(/^Same counter \((\d+)\) on two different payments$/, "Same payment number ($1) on two different payments")
      .replace(/^Counter (\d+) doesn't point back to counter (\d+)$/, "Payment $1 doesn't continue from payment $2")
      .replace(/^Running total went backwards: (\d+) < (\d+) cents$/,
        (_, x: string, y: string) => `Running total went backwards: ${usd(Number(x))} before, after ${usd(Number(y))} was already spent`);
    if (label.startsWith("CERT: ")) label = `The bank's certificate: ${label.slice(6)}`;
    else if (label.startsWith("TAG: ")) label = `Payment ${tags++ < 2 ? "A" : "B"}: ${label.slice(5)}`;
    else if (label.startsWith("DLOG: ")) label = `The shop's log entry: ${label.slice(6)}`;
    return { ...c, label };
  });
}
