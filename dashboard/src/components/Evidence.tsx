// Two conflicting tags side by side, and the in-browser "Verify it yourself"
// check list (spec §18.3, §18.6). Shared by the Cases tab and the proof page.
import { useState } from "react";
import type { SignedObj } from "../api";
import { dollars } from "../format";
import { b64uToBytes, bytesToHex, checkSigned, conflictingFields, ruleHolds, type Check, type Fields } from "../verify";

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

export interface VerifyInput {
  rule: string;
  cert: SignedObj;
  tagA: SignedObj;
  tagB: SignedObj;
  serverPubB64: string;
  accept?: SignedObj; // MERCHANT_KNEW: the merchant's own ACCEPT entry
}

/** Every check runs here, in this browser, with WebCrypto. */
export async function runChecks(input: VerifyInput): Promise<Check[]> {
  const { rule, cert, tagA, tagB, accept } = input;
  const serverPub = bytesToHex(b64uToBytes(input.serverPubB64));
  const holderPub = String(cert.fields.holder_pub); // certified by the server signature checked first
  const checks: Check[] = [
    ...(await checkSigned(cert, serverPub, `the StormCash server key ${serverPub.slice(0, 8)}…`)),
    ...(await checkSigned(tagA, holderPub, "the wallet key in the certificate")),
    ...(await checkSigned(tagB, holderPub, "the wallet key in the certificate")),
    {
      label: "Both payments spend this certificate",
      ok: tagA.fields.cert_id === cert.fields.cert_id && tagB.fields.cert_id === cert.fields.cert_id,
    },
  ];
  if (rule === "MERCHANT_KNEW") {
    // The two payments must themselves break R1–R3; report the first rule that holds.
    const results = await Promise.all(
      ["SAME_COUNTER", "BROKEN_LINK", "TOTAL_BACKWARDS"].map((r) => ruleHolds(r, tagA.fields as Fields, tagB.fields as Fields)),
    );
    checks.push(results.find((c) => c.ok) ?? { label: "The two payments conflict", ok: false });
  } else {
    checks.push(await ruleHolds(rule, tagA.fields as Fields, tagB.fields as Fields));
  }
  if (accept) {
    checks.push(...(await checkSigned(accept, String(accept.fields.device_pub), "the merchant's own key")));
    const held = (accept.fields.held_ids as string[]) ?? [];
    checks.push({
      label: "The merchant's log says it already held the other payment when it accepted",
      ok: accept.fields.tag_hash === tagB.digest && held.includes(tagA.digest),
    });
  }
  return checks;
}

export function VerifyPanel({ input, big = false }: { input: VerifyInput; big?: boolean }) {
  const [checks, setChecks] = useState<Check[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function verify() {
    if (!window.isSecureContext || !crypto?.subtle) {
      setError("This browser only verifies over HTTPS. Open the proof link from the QR code (https://…).");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setChecks(await runChecks(input));
    } catch (e) {
      setError(String(e));
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
