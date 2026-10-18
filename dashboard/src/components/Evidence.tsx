// The two conflicting tags as one table, the conflicting row tinted, and the
// in-browser "Verify it yourself" check (spec §18.3, §18.6). Shared by the
// Cases tab and the proof page.
import { useState, type ReactNode } from "react";
import type { SignedObj } from "../api";
import { conflictSentence, plainChecks } from "../cases";
import { dollars } from "../format";
import { conflictingFields, runChecks, type Check, type VerifyInput } from "../verify";
import { CopyId, Td } from "./ui";

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
  if (!checks) return <span className="text-th text-secondary">not checked yet</span>;
  const own = checks.slice(2 + side * 2, 4 + side * 2);
  const ok = own.length === 2 && own.every((c) => c.ok);
  return ok ? <span className="font-medium text-success">✓ Valid</span> : <span className="font-medium text-danger">✗ Invalid</span>;
}

/**
 * The two payments side by side: the certificate they share, then payment
 * number, amount, running total, the link back to the previous payment and each
 * signature. What conflicts is one sentence above and tinted coral in the
 * table. Raw fields sit under "Technical details". Ids are truncated; press one to copy it.
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
  const sameCert = !!b && a.fields.cert_id === b.fields.cert_id;
  const samePrev = !!b && a.fields.prev_hash === b.fields.prev_hash;
  const plain: [string, string, (t: SignedObj) => ReactNode][] = [
    ["cert_id", "Certificate", (t) => <CopyId value={String(t.fields.cert_id)} chars={12} />],
    ["counter", "Payment number", (t) => String(t.fields.counter)],
    ["amount_cents", "Amount", (t) => dollars(Number(t.fields.amount_cents))],
    ["cum_cents", "Running total", (t) => dollars(Number(t.fields.cum_cents))],
    ["prev_hash", "Points back to", (t) => <CopyId value={String(t.fields.prev_hash)} chars={12} />],
    ["sig", "Signature", (t) => <CopyId value={String(t.json.sig)} chars={12} />],
  ];
  const note: Record<string, ReactNode> = {
    cert_id: sameCert ? <span className="text-th text-success">same certificate, same wallet</span> : null,
    prev_hash: samePrev ? <span className="text-th text-secondary">both continue from the same payment</span> : null,
  };
  return (
    <div className="min-w-0">
      {sentence && <p className="rounded-t-[8px] border border-coral/50 bg-danger-tint px-3 py-2.5 font-semibold text-danger">{sentence}</p>}
      <div className={`overflow-hidden border border-rule ${sentence ? "rounded-b-[8px] border-t-0" : "rounded-[8px]"}`}>
        <table className="w-full table-fixed border-collapse text-left text-ui tabular-nums">
          <thead className="bg-surface">
            <tr className="text-th text-secondary">
              <th className="w-[30%] border-b border-rule px-3 py-2 font-semibold sm:w-[26%]">Signed field</th>
              <th className="border-b border-l border-rule px-3 py-2 font-semibold"><span className="block truncate">{titleA}</span></th>
              {b && <th className="border-b border-l border-rule px-3 py-2 font-semibold"><span className="block truncate">{titleB}</span></th>}
            </tr>
          </thead>
          <tbody>
            {plain.map(([key, label, show]) => {
              const inA = red.a.includes(key);
              const inB = red.b.includes(key);
              return (
                <tr key={key} className={inA || inB ? "bg-danger-tint" : undefined}>
                  <td className="border-b border-rule px-3 py-2 align-top text-secondary">
                    {label}
                    {note[key] && <span className="mt-0.5 block">{note[key]}</span>}
                  </td>
                  {tags.map((t, i) => (
                    <td key={t.digest} className={`min-w-0 border-b border-l border-rule px-3 py-2 align-top ${(i === 0 ? inA : inB) ? "font-semibold text-danger [&_button]:text-danger" : ""}`}>
                      {show(t)}
                    </td>
                  ))}
                </tr>
              );
            })}
            <tr>
              <td className="px-3 py-2 text-secondary">Signature check</td>
              {tags.map((t, i) => <td key={t.digest} className="border-l border-rule px-3 py-2">{validity(checks, i as 0 | 1)}</td>)}
            </tr>
          </tbody>
        </table>
      </div>
      <details className="mt-2">
        <summary className="cursor-pointer py-2 text-accent">Technical details</summary>
        <table className="w-full table-fixed border-collapse text-left text-th">
          <tbody>
            {RAW.map(([key, label, show]) => (
              <tr key={key}>
                <Td className="break-all pl-3 font-mono text-th text-secondary">{label}</Td>
                {tags.map((t, i) => (
                  <Td key={t.digest} className={`break-all font-mono text-th ${(i === 0 ? red.a : red.b).includes(key) ? "font-semibold text-danger" : ""}`}>
                    {show(t.fields[key])}
                  </Td>
                ))}
              </tr>
            ))}
            <tr>
              <Td className="break-all pl-3 font-mono text-th text-secondary">tag id</Td>
              {tags.map((t) => <Td key={t.digest}><CopyId value={t.digest} chars={12} /></Td>)}
            </tr>
          </tbody>
        </table>
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
