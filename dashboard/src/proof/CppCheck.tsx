// The proof page's second check (spec §18.6): the C++ verifier's verdict, and
// whether it agrees with the WebCrypto check above it. See cppverify.ts.
import { StatusItem, type Tone } from "../components/ui";
import type { Agreement, CppVerdict } from "../cppverify";

export type CppState =
  | { kind: "running" }
  | { kind: "done"; verdict: CppVerdict }
  | { kind: "unavailable"; reason: string; detail?: string };

const HEADLINE: Record<"proven" | "incomplete" | "invalid", { text: string; color: string; pill: string; tone: Tone }> = {
  proven: { text: "Verified ✓", color: "text-success", pill: "Valid", tone: "success" },
  incomplete: {
    text: "Signatures valid, but this proof doesn't show the whole claim",
    color: "text-warning",
    pill: "Incomplete",
    tone: "warning",
  },
  invalid: { text: "Something didn't verify ✗", color: "text-danger", pill: "Rejected", tone: "danger" },
};

/** The C++ verdict as a short pill for the "Checked on your phone" rows. */
export function cppPill(state: CppState): { tone: Tone; text: string } {
  if (state.kind === "running") return { tone: "neutral", text: "Checking…" };
  if (state.kind === "unavailable") return { tone: "warning", text: "C++ check unavailable" };
  const head = HEADLINE[state.verdict.status as keyof typeof HEADLINE] ?? HEADLINE.invalid;
  return { tone: head.tone, text: head.pill };
}

/** The C++ verifier's full answer, under the WebCrypto result. */
export function CppCheck({ state }: { state: CppState }) {
  return (
    <section aria-live="polite">
      <h2 className="border-b border-rule pb-2 text-section font-medium text-heading">
        Checked again by our independent C++ verifier (WebAssembly)
      </h2>
      {state.kind === "running" && <p className="py-2.5 text-secondary">Checking…</p>}
      {state.kind === "unavailable" && (
        <div className="py-2.5">
          <p className="font-semibold text-warning">C++ check unavailable</p>
          <p className="mt-1 break-words text-th text-secondary">
            {state.reason} The WebCrypto result above doesn't depend on it.
          </p>
          {state.detail && <p className="mt-1 text-th wrap-anywhere text-secondary">{state.detail}</p>}
        </div>
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
    <div className="py-2.5">
      <p className={`font-semibold ${head.color}`}>{head.text}</p>
      {v.status === "invalid" && failed.length > 0 ? (
        // The checks that failed, marked as failed (the CLI's verdict quotes the first one).
        <ul className="mt-1 space-y-1 text-th">
          {failed.map((l, i) => (
            <li key={i} className="flex gap-2">
              <span className="text-danger">✗</span>
              <span className="min-w-0 wrap-anywhere text-ink">{l.text}</span>
            </li>
          ))}
        </ul>
      ) : null}
      <details className="mt-3 text-th">
        <summary className="cursor-pointer py-1 text-accent">All {lines.length} checks the C++ verifier ran</summary>
        <p className="mt-2 break-words text-ink">{v.verdict}</p>
        <ul className="mt-2 border-t border-rule">
          {lines.map((l, i) => (
            <li key={i} className="flex gap-2 border-b border-rule py-1.5">
              <span className={l.ok ? "text-success" : "text-danger"}>{l.ok ? "✓" : "✗"}</span>
              <span className="min-w-0 font-mono text-th wrap-anywhere text-ink">{l.text}</span>
            </li>
          ))}
        </ul>
        {(v.notes ?? []).map((n, i) => (
          <p key={i} className="mt-2 break-words text-secondary">
            Note: {n}
          </p>
        ))}
        <p className="mt-2 text-secondary">
          The same verdict as <code>stormcash-verify proof</code>. Crypto: {v.crypto}, not the browser's.
        </p>
      </details>
    </div>
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
      <div role="status" className="mt-3 rounded-2xl bg-success-bg px-4 py-3.5">
        <StatusItem tone="success">
          <span className="font-semibold text-success">Verified by 2 independent implementations</span>
        </StatusItem>
        <p className="mt-1 text-th text-ink">
          Your browser's WebCrypto and our C++ verifier each checked every signature and the rule, with no code in
          common.
        </p>
      </div>
    );
  }
  if (result === "neither_verified") {
    return (
      <div role="status" className="mt-3 rounded-2xl bg-danger-bg px-4 py-3.5">
        <StatusItem tone="danger">
          <span className="font-semibold text-danger">Neither implementation verified this proof</span>
        </StatusItem>
        <p className="mt-1 text-th text-ink">
          {WEB_WORDS(webOk)}, and {CPP_WORDS[cpp?.status ?? "invalid"]}. The details are below.
        </p>
      </div>
    );
  }
  return (
    <div role="alert" className="mt-3 rounded-2xl bg-warning-bg px-4 py-3.5">
      <StatusItem tone="warning">
        <span className="font-semibold text-warning">The two implementations disagree</span>
      </StatusItem>
      <p className="mt-1 text-th text-ink">
        {WEB_WORDS(webOk)}, but {CPP_WORDS[cpp?.status ?? "invalid"]}. Treat this proof as unverified until that's
        explained.
      </p>
    </div>
  );
}
