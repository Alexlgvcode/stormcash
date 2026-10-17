// The proof page's second check (spec §18.6): the C++ verifier's verdict, and
// whether it agrees with the WebCrypto check above it. See cppverify.ts.
import type { Agreement, CppVerdict } from "../cppverify";

export type CppState =
  | { kind: "running" }
  | { kind: "done"; verdict: CppVerdict }
  | { kind: "unavailable"; reason: string; detail?: string };

const HEADLINE: Record<"proven" | "incomplete" | "invalid", { text: string; color: string }> = {
  proven: { text: "Verified ✓", color: "text-emerald-300" },
  incomplete: { text: "Signatures valid, but this proof doesn't show the whole claim", color: "text-amber-300" },
  invalid: { text: "Something didn't verify ✗", color: "text-rose-300" },
};

export function CppCheck({ state }: { state: CppState }) {
  return (
    <section className="rounded-xl border border-slate-700 bg-slate-900 p-4" aria-live="polite">
      <h2 className="text-base font-semibold text-slate-200">
        Checked again by our independent C++ verifier (WebAssembly)
      </h2>
      {state.kind === "running" && <p className="mt-2 text-lg text-slate-300">Checking…</p>}
      {state.kind === "unavailable" && (
        <>
          <p className="mt-2 text-lg font-bold text-amber-300">C++ check unavailable</p>
          <p className="mt-1 break-words text-sm text-slate-400">
            {state.reason} The WebCrypto result above doesn't depend on it.
          </p>
          {state.detail && <p className="mt-1 text-xs wrap-anywhere text-slate-500">{state.detail}</p>}
        </>
      )}
      {state.kind === "done" && <Verdict v={state.verdict} />}
    </section>
  );
}

function Verdict({ v }: { v: CppVerdict }) {
  const head = HEADLINE[v.status as keyof typeof HEADLINE] ?? HEADLINE.invalid;
  const lines = v.lines ?? [];
  const failed = lines.filter((l) => !l.ok);
  return (
    <>
      <p className={`mt-2 text-xl font-bold ${head.color}`}>{head.text}</p>
      {v.status === "invalid" && failed.length > 0 ? (
        // The checks that failed, marked as failed (the CLI's verdict quotes the first one).
        <ul className="mt-1 space-y-1 text-sm">
          {failed.map((l, i) => (
            <li key={i} className="flex gap-2">
              <span className="text-rose-400">✗</span>
              <span className="min-w-0 wrap-anywhere text-slate-300">{l.text}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1 break-words text-sm text-slate-300">{v.verdict}</p>
      )}
      <details className="mt-3 text-sm">
        <summary className="cursor-pointer py-1 text-sky-300">All {lines.length} checks the C++ verifier ran</summary>
        <ul className="mt-2 space-y-1">
          {lines.map((l, i) => (
            <li key={i} className="flex gap-2">
              <span className={l.ok ? "text-emerald-400" : "text-rose-400"}>{l.ok ? "✓" : "✗"}</span>
              <span className="min-w-0 font-mono text-xs wrap-anywhere text-slate-300">{l.text}</span>
            </li>
          ))}
        </ul>
        {(v.notes ?? []).map((n, i) => (
          <p key={i} className="mt-2 break-words text-xs text-slate-400">
            Note: {n}
          </p>
        ))}
        <p className="mt-2 text-xs text-slate-500">
          The same verdict as <code>stormcash-verify proof</code>. Crypto: {v.crypto}, not the browser's.
        </p>
      </details>
    </>
  );
}

const WEB_WORDS = (ok: boolean) => (ok ? "WebCrypto verified it" : "WebCrypto didn't verify it");
const CPP_WORDS: Record<string, string> = {
  proven: "the C++ verifier proved it",
  incomplete: "the C++ verifier found the signatures valid but the claim not fully shown",
  invalid: "the C++ verifier rejected it",
};

export function AgreementLine({ result, webOk, cpp }: { result: Agreement; webOk: boolean; cpp: CppVerdict | null }) {
  if (result === "cpp_unavailable") return null;
  if (result === "both_verified") {
    return (
      <div className="rounded-xl border-2 border-emerald-500/60 bg-emerald-500/10 p-4" role="status">
        <p className="text-xl font-bold text-emerald-300">Verified by 2 independent implementations ✓</p>
        <p className="mt-1 text-base text-slate-300">
          Your browser's WebCrypto and our C++ verifier each checked every signature and the rule, with no code in
          common.
        </p>
      </div>
    );
  }
  if (result === "neither_verified") {
    return (
      <div className="rounded-xl border-2 border-rose-500/60 bg-rose-500/10 p-4" role="status">
        <p className="text-xl font-bold text-rose-300">Neither implementation verified this proof</p>
        <p className="mt-1 text-base text-slate-300">
          {WEB_WORDS(webOk)}, and {CPP_WORDS[cpp?.status ?? "invalid"]}. The details are above.
        </p>
      </div>
    );
  }
  return (
    <div className="rounded-xl border-2 border-amber-400/70 bg-amber-400/10 p-4" role="alert">
      <p className="text-xl font-bold text-amber-300">The two implementations disagree</p>
      <p className="mt-1 text-base text-slate-300">
        {WEB_WORDS(webOk)}, but {CPP_WORDS[cpp?.status ?? "invalid"]}. Treat this proof as unverified until that's
        explained.
      </p>
    </div>
  );
}
