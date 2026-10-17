// Two conflicting tags side by side, and the in-browser "Verify it yourself"
// check list (spec §18.3, §18.6). Shared by the Cases tab and the proof page.
import { useState } from "react";
import type { SignedObj } from "../api";
import { dollars } from "../format";
import { conflictingFields, runChecks, type Check, type VerifyInput } from "../verify";

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

export function TagCard({ title, tag, red }: { title: string; tag: SignedObj; red: string[] }) {
  return (
    <div className="rounded-2xl border border-slate-700 bg-slate-900 p-4">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <h3 className="text-lg font-semibold text-white">{title}</h3>
        <span className="font-mono text-xs text-slate-400">tag {short(tag.digest)}</span>
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-base">
        {ROWS.map(([key, label, show]) => (
          <div key={key} className="contents">
            <dt className="text-slate-400">{label}</dt>
            <dd
              className={`text-right font-mono ${
                red.includes(key) ? "rounded bg-rose-500/20 px-1 font-bold text-rose-300" : "text-slate-100"
              }`}
            >
              {show(tag.fields[key])}
            </dd>
          </div>
        ))}
      </dl>
      <div className="mt-2 truncate font-mono text-xs text-slate-500" title={String(tag.json.sig)}>
        signature {String(tag.json.sig).slice(0, 24)}…
      </div>
    </div>
  );
}

export function TagPair({ rule, a, b }: { rule: string; a: SignedObj; b: SignedObj }) {
  const red = conflictingFields(rule);
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <TagCard title="Payment A" tag={a} red={red.a} />
      <TagCard title="Payment B" tag={b} red={red.b} />
    </div>
  );
}

export function VerifyPanel({
  input,
  big = false,
  onStart,
  onDone,
}: {
  input: VerifyInput;
  big?: boolean;
  onStart?: () => void; // the button was pressed (the proof page starts its C++ check)
  onDone?: (checks: Check[] | null) => void; // null: WebCrypto couldn't run the checks
}) {
  const [checks, setChecks] = useState<Check[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function verify() {
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

  const allOk = checks !== null && checks.every((c) => c.ok);
  return (
    <div className="space-y-3">
      <button
        onClick={verify}
        disabled={busy}
        className={`w-full rounded-xl bg-sky-500 font-bold text-slate-950 hover:bg-sky-400 disabled:opacity-60 ${
          big ? "py-5 text-2xl" : "py-3 text-lg"
        }`}
      >
        {busy ? "Verifying…" : "Verify it yourself"}
      </button>
      {error && <p className="text-rose-300">{error}</p>}
      {checks && (
        <div className={`rounded-xl border-2 p-4 ${allOk ? "border-emerald-500/60" : "border-rose-500/60"}`}>
          <p className={`mb-2 text-xl font-bold ${allOk ? "text-emerald-300" : "text-rose-300"}`}>
            {allOk ? "Verified in this browser ✓" : "Something didn't verify ✗"}
          </p>
          <ul className="space-y-1">
            {checks.map((c, i) => (
              <li key={i} className="flex gap-2 text-base">
                <span className={c.ok ? "text-emerald-400" : "text-rose-400"}>{c.ok ? "✓" : "✗"}</span>
                <span className="text-slate-200">
                  {c.label}
                  {c.detail && <span className="block font-mono text-xs text-slate-400">{c.detail}</span>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
