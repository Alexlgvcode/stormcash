// Public proof page /proof/:caseId (spec §18.6): mobile-friendly, no login.
// A judge scans the Proof QR and verifies the signatures on their own phone.
// WebCrypto is the primary check; the C++ verifier (WebAssembly) checks again.
import { useEffect, useRef, useState } from "react";
import { getJSON, type Proof } from "../api";
import { CheckList, RULE_TEXT, TagTable, useVerify } from "../components/Evidence";
import { Button, Eyebrow, Pill, Section, type Tone } from "../components/ui";
import { agreement, checkWithCpp, loadCppVerifier } from "../cppverify";
import { AgreementLine, CppCheck, cppPill, type CppState } from "./CppCheck";

// The server key this page trusts. A build for the demo bakes it in
// (VITE_SERVER_PUB, base64url); otherwise the page says where the key came from.
const BAKED_SERVER_PUB: string | undefined = import.meta.env.VITE_SERVER_PUB;

type Web = "running" | "ok" | "failed" | "unavailable";
const WEB_PILL: Record<Web, { tone: Tone; text: string }> = {
  running: { tone: "neutral", text: "Checking…" },
  ok: { tone: "success", text: "Valid" },
  failed: { tone: "danger", text: "Didn't verify" },
  unavailable: { tone: "warning", text: "Couldn't run" },
};

export function ProofPage({ caseId }: { caseId: number }) {
  const [proof, setProof] = useState<Proof | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The second check, run with the first on each press: null until then.
  const [web, setWeb] = useState<Web | null>(null);
  const [cpp, setCpp] = useState<CppState | null>(null);
  const run = useRef(0);

  useEffect(() => {
    getJSON<Proof>(`/v1/proof/${caseId}`).then(setProof).catch((e) => setError(String(e)));
    // Fetch the WebAssembly now so the C++ check is ready when the button is pressed.
    loadCppVerifier().catch(() => {});
  }, [caseId]);

  const accept = proof?.rule === "MERCHANT_KNEW" ? proof.log_entries.find((e) => e.fields.kind === "ACCEPT") : undefined;
  const serverPub = BAKED_SERVER_PUB ?? proof?.server_pub;

  function startCppCheck() {
    if (!proof) return;
    const id = ++run.current;
    setWeb("running");
    setCpp({ kind: "running" });
    // The same key the WebCrypto check uses: the baked one, or else the file's own.
    checkWithCpp(proof, BAKED_SERVER_PUB)
      .then((verdict) => {
        if (id !== run.current) return;
        setCpp(
          verdict.status === "error"
            ? { kind: "unavailable", reason: "It couldn't read this proof.", detail: verdict.error }
            : { kind: "done", verdict },
        );
      })
      .catch((e) => {
        if (id !== run.current) return;
        const reason =
          typeof WebAssembly === "undefined"
            ? "This browser doesn't run WebAssembly."
            : "The WebAssembly module didn't load or run in this browser.";
        setCpp({ kind: "unavailable", reason, detail: String(e) });
      });
  }

  const { checks, busy, error: webError, verify } = useVerify(
    proof && serverPub
      ? { rule: proof.rule, cert: proof.cert, tagA: proof.tag_a, tagB: proof.tag_b, serverPubB64: serverPub, accept }
      : null,
    startCppCheck,
    (result) => setWeb(result === null ? "unavailable" : result.every((c) => c.ok) ? "ok" : "failed"),
  );

  if (error) return <p className="px-4 py-6 text-danger">This proof isn't available: {error}</p>;
  if (!proof) return <p className="px-4 py-6 text-secondary">Loading proof…</p>;
  const text = RULE_TEXT[proof.rule] ?? { title: proof.rule, why: "" };
  const cppVerdict = cpp?.kind === "done" ? cpp.verdict : null;
  const bothFinished = (web === "ok" || web === "failed") && cpp !== null && cpp.kind !== "running";

  return (
    <>
    <div className="border-b border-rule px-4 py-3.5 text-[18px] font-bold text-heading">StormCash</div>
    <main className="mx-auto max-w-xl space-y-8 px-4 py-6">
      <header>
        <Eyebrow>Case #{proof.case_id}</Eyebrow>
        <h1 className="mt-1 text-[28px] leading-tight font-light text-heading">{text.title}</h1>
        <p className="mt-2 text-ink">{text.why}</p>
      </header>

      <div className="space-y-2">
        <Button primary disabled={busy} onClick={verify} className="w-full py-3 text-[18px]">
          {busy ? "Verifying…" : web ? "Verify again" : "Verify it yourself"}
        </Button>
        {webError && <p className="text-danger">{webError}</p>}
      </div>

      {web && (
        <Section title="Checked on your phone">
          <ul>
            <li className="flex items-center justify-between gap-4 border-b border-rule py-2.5">
              <span className="text-ink">Your browser (WebCrypto)</span>
              <Pill tone={WEB_PILL[web].tone}>{WEB_PILL[web].text}</Pill>
            </li>
            {cpp && (
              <li className="flex items-center justify-between gap-4 border-b border-rule py-2.5">
                <span className="text-ink">Our C++ verifier (WebAssembly)</span>
                <Pill tone={cppPill(cpp).tone}>{cppPill(cpp).text}</Pill>
              </li>
            )}
          </ul>
          {bothFinished && (
            <AgreementLine result={agreement(web === "ok", cppVerdict)} webOk={web === "ok"} cpp={cppVerdict} />
          )}
        </Section>
      )}

      {checks && (
        <Section title={checks.every((c) => c.ok) ? "Verified in this browser ✓" : "Something didn't verify ✗"}>
          <CheckList checks={checks} />
        </Section>
      )}
      {cpp && <CppCheck state={cpp} />}

      <Section title="The two payments">
        <TagTable rule={proof.rule === "MERCHANT_KNEW" ? "" : proof.rule} a={proof.tag_a} b={proof.tag_b} checks={checks} />
      </Section>

      <p className="text-ink">
        Both payments carry the same phone's signature, and the bank's server certified that phone's key for this
        wallet. Two signatures on the same money can't both be honest, so this proves the double spend without
        trusting StormCash: your browser checked every signature itself.
      </p>
      <p className="text-th text-secondary">
        {BAKED_SERVER_PUB ? "Server key built into this page." : "Server key as reported by this server."} Checks
        use WebCrypto ECDSA P-256 / SHA-256 over the exact signed text. The second check is our C++ verifier
        (stormcash-verify) compiled to WebAssembly, with its own P-256 (p256-m) and SHA-256.
      </p>
    </main>
    </>
  );
}
