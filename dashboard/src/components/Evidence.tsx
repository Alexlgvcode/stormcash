// The two conflicting tags as one table, the conflicting row tinted, and the
// in-browser "Verify it yourself" check (spec §18.3, §18.6). Shared by the
// Cases tab and the proof page.
import { useState } from "react";
import type { SignedObj } from "../api";
import { dollars } from "../format";
import { conflictingFields, runChecks, type Check, type VerifyInput } from "../verify";
import { Table, Td, Th } from "./ui";

export const RULE_TEXT: Record<string, { title: string; why: string }> = {
  SAME_COUNTER: {
    title: "Same counter used twice",
    why: "The wallet signed two different payments with the same counter: the same money was spent twice.",
  },
  BROKEN_LINK: {
    title: "Broken link",
    why: "The next payment doesn't point back to the previous one: the wallet was rolled back and forked.",
  },
  TOTAL_BACKWARDS: {
    title: "Running total went backwards",
    why: "A later payment claims less was spent before it than an earlier payment already had: a counter was skipped.",
  },
  OVER_CAP: { title: "Over the certificate cap", why: "Settled payments add up to more than any cap ever issued." },
  MERCHANT_KNEW: {
    title: "Merchant knew",
    why: "The shop accepted a double spend while its own signed log shows it already held the conflicting payment.",
  },
  LOG_TAMPER: { title: "Device log tampered", why: "A device's signed, hash-chained log was forked or rewritten." },
};

const short = (hex: string) => `${hex.slice(0, 10)}…`;

const ROWS: [string, string, (v: unknown) => string][] = [
  ["counter", "Counter", String],
  ["amount_cents", "Amount", (v) => dollars(v as number)],
  ["cum_cents", "Running total", (v) => dollars(v as number)],
  ["prev_hash", "Points back to", (v) => short(String(v))],
  ["details_hash", "Payment details", (v) => short(String(v))],
];

/**
 * Field | Payment A | Payment B. A row holding the field the rule is about is
 * tinted, and the conflicting value is red. `b` is optional (a single settled tag).
 */
export function TagTable({ rule, a, b, titleA = "Payment A", titleB = "Payment B" }: {
  rule: string;
  a: SignedObj;
  b?: SignedObj | null;
  titleA?: string;
  titleB?: string;
}) {
  const red = b ? conflictingFields(rule) : { a: ["cum_cents"], b: [] };
  const cell = (tag: SignedObj, key: string, show: (v: unknown) => string, isRed: boolean) => (
    <Td className={`whitespace-nowrap tabular-nums ${isRed ? "font-semibold text-danger" : ""}`}>
      <span className="font-mono text-th">{show(tag.fields[key])}</span>
    </Td>
  );
  return (
    <Table>
      <thead>
        <tr>
          <Th className="pl-3">Field</Th>
          <Th>{titleA}</Th>
          {b && <Th>{titleB}</Th>}
        </tr>
      </thead>
      <tbody>
        {ROWS.map(([key, label, show]) => {
          const inA = red.a.includes(key);
          const inB = red.b.includes(key);
          return (
            <tr key={key} className={inA || inB ? "bg-danger-tint" : undefined}>
              <Td className="pl-3 text-secondary">{label}</Td>
              {cell(a, key, show, inA)}
              {b && cell(b, key, show, inB)}
            </tr>
          );
        })}
        <tr>
          <Td className="pl-3 text-secondary">Signature</Td>
          {[a, b].filter((t): t is SignedObj => !!t).map((t) => (
            <Td key={t.digest} className="max-w-0 truncate font-mono text-th" title={String(t.json.sig)}>
              {String(t.json.sig).slice(0, 24)}…
            </Td>
          ))}
        </tr>
        <tr>
          <Td className="pl-3 text-secondary">Tag</Td>
          {[a, b].filter((t): t is SignedObj => !!t).map((t) => (
            <Td key={t.digest} className="font-mono text-th">{short(t.digest)}</Td>
          ))}
        </tr>
      </tbody>
    </Table>
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
      {checks.map((c, i) => (
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
