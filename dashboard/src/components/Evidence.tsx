// The two conflicting tags as one table, the conflicting row tinted, and the
// in-browser "Verify it yourself" check (spec §18.3, §18.6). Shared by the
// Cases tab and the proof page.
import { useState, type ReactNode } from "react";
import type { SignedObj } from "../api";
import { conflictSentence, plainChecks } from "../cases";
import { dollars } from "../format";
import { conflictingFields, runChecks, type Check, type VerifyInput } from "../verify";
import { Table, Td, Th } from "./ui";

export const RULE_TEXT: Record<string, { title: string; why: string }> = {
  SAME_COUNTER: {
    title: "Same payment number used twice",
    why: "The wallet signed two different payments with the same payment number: the same money was spent twice.",
  },
  BROKEN_LINK: {
    title: "Payment chain broken",
    why: "A payment doesn't continue from the one before it: the wallet was rolled back and the money spent again.",
  },
  TOTAL_BACKWARDS: {
    title: "Running total went backwards",
    why: "A later payment claims less was spent before it than an earlier payment already had: a payment number was skipped.",
  },
  OVER_CAP: { title: "Spent over the limit", why: "Settled payments add up to more than any limit this wallet was ever given." },
  MERCHANT_KNEW: {
    title: "Shop accepted it knowingly",
    why: "The shop accepted a double spend while its own signed log shows it already held the conflicting payment.",
  },
  LOG_TAMPER: { title: "Device log altered", why: "A device's signed, chained log was forked or rewritten." },
};

const short = (hex: string) => `${hex.slice(0, 10)}…`;

// The raw signed fields, for the Technical details.
const RAW: [string, string, (v: unknown) => string][] = [
  ["counter", "counter", String],
  ["amount_cents", "amount_cents", String],
  ["cum_cents", "cum_cents", String],
  ["prev_hash", "prev_hash (points back to)", (v) => short(String(v))],
  ["details_hash", "details_hash", (v) => short(String(v))],
];

/** ✓ Valid / ✗ Invalid once the browser checked it (runChecks order: certificate, then A's two, then B's two). */
function validity(checks: Check[] | null, side: 0 | 1): ReactNode {
  if (!checks) return <span className="text-secondary">Press Verify it yourself</span>;
  const own = checks.slice(2 + side * 2, 4 + side * 2);
  const ok = own.length === 2 && own.every((c) => c.ok);
  return ok ? <span className="font-medium text-success">✓ Valid</span> : <span className="font-medium text-danger">✗ Invalid</span>;
}

/**
 * The two payments in plain words: what conflicts as one sentence, then
 * payment number, amount, running total and signature validity. The raw signed
 * fields, signatures and tag ids sit under "Technical details".
 */
export function TagTable({ rule, a, b, titleA = "Payment A", titleB = "Payment B", checks = null }: {
  rule: string;
  a: SignedObj;
  b?: SignedObj | null;
  titleA?: string;
  titleB?: string;
  checks?: Check[] | null;
}) {
  const red = b ? conflictingFields(rule) : { a: ["cum_cents"], b: [] };
  const sentence = conflictSentence(rule, a.fields, b?.fields);
  const tags = [a, b].filter((t): t is SignedObj => !!t);
  const plain: [string, string, (t: SignedObj) => ReactNode][] = [
    ["counter", "Payment number", (t) => String(t.fields.counter)],
    ["amount_cents", "Amount", (t) => dollars(Number(t.fields.amount_cents))],
    ["cum_cents", "Running total", (t) => dollars(Number(t.fields.cum_cents))],
  ];
  return (
    <div>
      {sentence && <p className="border-b border-rule bg-danger-tint px-3 py-2.5 font-medium text-danger">{sentence}</p>}
      <Table>
        <thead>
          <tr>
            <Th className="pl-3">Field</Th>
            <Th>{titleA}</Th>
            {b && <Th>{titleB}</Th>}
          </tr>
        </thead>
        <tbody>
          {plain.map(([key, label, show]) => {
            const inA = red.a.includes(key);
            const inB = red.b.includes(key);
            return (
              <tr key={key} className={inA || inB ? "bg-danger-tint" : undefined}>
                <Td className="pl-3 text-secondary">{label}</Td>
                {tags.map((t, i) => (
                  <Td key={t.digest} className={`tabular-nums ${(i === 0 ? inA : inB) ? "font-semibold text-danger" : ""}`}>
                    {show(t)}
                  </Td>
                ))}
              </tr>
            );
          })}
          <tr>
            <Td className="pl-3 text-secondary">Signature</Td>
            {tags.map((t, i) => <Td key={t.digest}>{validity(checks, i as 0 | 1)}</Td>)}
          </tr>
        </tbody>
      </Table>
      <details className="mt-3">
        <summary className="cursor-pointer py-1 text-accent">Technical details</summary>
        <Table>
          <tbody>
            {RAW.map(([key, label, show]) => (
              <tr key={key}>
                <Td className="pl-3 font-mono text-th text-secondary">{label}</Td>
                {tags.map((t, i) => (
                  <Td key={t.digest} className={`font-mono text-th ${(i === 0 ? red.a : red.b).includes(key) ? "font-semibold text-danger" : ""}`}>
                    {show(t.fields[key])}
                  </Td>
                ))}
              </tr>
            ))}
            <tr>
              <Td className="pl-3 font-mono text-th text-secondary">sig</Td>
              {tags.map((t) => (
                <Td key={t.digest} className="max-w-0 truncate font-mono text-th" title={String(t.json.sig)}>
                  {String(t.json.sig).slice(0, 24)}…
                </Td>
              ))}
            </tr>
            <tr>
              <Td className="pl-3 font-mono text-th text-secondary">tag id</Td>
              {tags.map((t) => <Td key={t.digest} className="font-mono text-th">{short(t.digest)}</Td>)}
            </tr>
          </tbody>
        </Table>
      </details>
    </div>
  );
}

/**
 * The WebCrypto check (spec §18.6). `onStart` fires when it's asked to run (the
 * proof page starts its C++ check then); `onDone` gets the checks, or null when
 * WebCrypto couldn't run them.
 */
export function useVerify(input: VerifyInput | null, onStart?: () => void, onDone?: (checks: Check[] | null) => void) {
  const [checks, setChecks] = useState<Check[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function verify() {
    if (!input) return;
    onStart?.();
    if (!window.isSecureContext || !crypto?.subtle) {
      setError("This browser only verifies over HTTPS. Open the proof link from the QR code (https://…).");
      onDone?.(null);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await runChecks(input);
      setChecks(result);
      onDone?.(result);
    } catch (e) {
      setError(String(e));
      onDone?.(null);
    } finally {
      setBusy(false);
    }
  }

  return { checks, busy, error, verify };
}

/** The checks the browser ran, one ruled row each. */
export function CheckList({ checks }: { checks: Check[] }) {
  return (
    <ul className="border-t border-rule">
      {plainChecks(checks).map((c, i) => (
        <li key={i} className="grid grid-cols-[1.25rem_minmax(0,1fr)] gap-3 border-b border-rule py-2">
          <span className={c.ok ? "text-success" : "text-danger"}>{c.ok ? "✓" : "✗"}</span>
          <span className="min-w-0 text-ink">
            {c.label}
            {c.detail && <span className="block break-words font-mono text-th text-secondary">{c.detail}</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** "Verified in this browser ✓" and the checks, or why it couldn't run. */
export function VerifyResult({ checks, error }: { checks: Check[] | null; error: string | null }) {
  if (error) return <p className="text-danger">{error}</p>;
  if (!checks) return null;
  const allOk = checks.every((c) => c.ok);
  return (
    <div>
      <p className={`py-2 font-semibold ${allOk ? "text-success" : "text-danger"}`}>
        {allOk ? "Verified in this browser ✓" : "Something didn't verify ✗"}
      </p>
      <CheckList checks={checks} />
    </div>
  );
}
