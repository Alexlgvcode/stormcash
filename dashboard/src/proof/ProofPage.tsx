// Public proof page /proof/:caseId (spec §18.6): mobile-friendly, no login.
// A judge scans the Proof QR and verifies the signatures on their own phone.
import { useEffect, useRef, useState } from "react";
import { getJSON, type Proof } from "../api";
import { RULE_TEXT, TagPair, VerifyPanel } from "../components/Evidence";
import { agreement, checkWithCpp, loadCppVerifier } from "../cppverify";
import { AgreementLine, CppCheck, type CppState } from "./CppCheck";

// The server key this page trusts. A build for the demo bakes it in
// (VITE_SERVER_PUB, base64url); otherwise the page says where the key came from.
const BAKED_SERVER_PUB: string | undefined = import.meta.env.VITE_SERVER_PUB;

export function ProofPage({ caseId }: { caseId: number }) {
  const [proof, setProof] = useState<Proof | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The second check, run with the first on each press: null until then.
  const [web, setWeb] = useState<"running" | "ok" | "failed" | "unavailable" | null>(null);
  const [cpp, setCpp] = useState<CppState | null>(null);
  const run = useRef(0);

  useEffect(() => {
    getJSON<Proof>(`/v1/proof/${caseId}`).then(setProof).catch((e) => setError(String(e)));
    // Fetch the WebAssembly now so the C++ check is ready when the button is pressed.
    loadCppVerifier().catch(() => {});
  }, [caseId]);

  if (error) return <p className="p-6 text-lg text-rose-300">This proof isn't available: {error}</p>;
  if (!proof) return <p className="p-6 text-lg text-slate-300">Loading proof…</p>;
  const text = RULE_TEXT[proof.rule] ?? { title: proof.rule, why: "" };
  const accept = proof.rule === "MERCHANT_KNEW" ? proof.log_entries.find((e) => e.fields.kind === "ACCEPT") : undefined;
  const serverPub = BAKED_SERVER_PUB ?? proof.server_pub;

  function startCppCheck() {
    const id = ++run.current;
    setWeb("running");
    setCpp({ kind: "running" });
    // The same key the WebCrypto check uses: the baked one, or else the file's own.
    checkWithCpp(proof, BAKED_SERVER_PUB)
      .then((verdict) => {
        if (id !== run.current) return;
        setCpp(
          verdict.status === "error"
            ? { kind: "unavailable", reason: `It couldn't read this proof: ${verdict.error}.` }
            : { kind: "done", verdict },
        );
      })
      .catch((e) => {
        if (id !== run.current) return;
        const reason =
          typeof WebAssembly === "undefined"
            ? "This browser doesn't run WebAssembly."
            : `The WebAssembly module didn't load or run (${String(e)}).`;
        setCpp({ kind: "unavailable", reason });
      });
  }

  const cppVerdict = cpp?.kind === "done" ? cpp.verdict : null;
  const bothFinished = (web === "ok" || web === "failed") && cpp !== null && cpp.kind !== "running";

  return (
    <main className="mx-auto max-w-xl space-y-5 px-4 py-6">
      <header>
        <p className="text-sm font-semibold tracking-wide text-sky-400">STORMCASH · PROOF #{proof.case_id}</p>
        <h1 className="mt-1 text-3xl font-bold text-white">{text.title}</h1>
        <p className="mt-2 text-lg text-slate-300">{text.why}</p>
      </header>
      <TagPair rule={proof.rule === "MERCHANT_KNEW" ? "" : proof.rule} a={proof.tag_a} b={proof.tag_b} />
      <VerifyPanel
        big
        input={{ rule: proof.rule, cert: proof.cert, tagA: proof.tag_a, tagB: proof.tag_b, serverPubB64: serverPub, accept }}
        onStart={startCppCheck}
        onDone={(checks) => setWeb(checks === null ? "unavailable" : checks.every((c) => c.ok) ? "ok" : "failed")}
      />
      {cpp && <CppCheck state={cpp} />}
      {bothFinished && (
        <AgreementLine result={agreement(web === "ok", cppVerdict)} webOk={web === "ok"} cpp={cppVerdict} />
      )}
      <p className="text-base text-slate-300">
        Both payments carry the same phone's signature, and the bank's server certified that phone's key for this
        wallet. Two signatures on the same money can't both be honest, so this proves the double spend without
        trusting StormCash: your browser checked every signature itself.
      </p>
      <p className="text-xs text-slate-500">
        {BAKED_SERVER_PUB ? "Server key built into this page." : "Server key as reported by this server."} Checks
        use WebCrypto ECDSA P-256 / SHA-256 over the exact signed text. The second check is our C++ verifier
        (stormcash-verify) compiled to WebAssembly, with its own P-256 (p256-m) and SHA-256.
      </p>
    </main>
  );
}
