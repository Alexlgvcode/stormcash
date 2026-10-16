// Public proof page /proof/:caseId (spec §18.6): mobile-friendly, no login.
// A judge scans the Proof QR and verifies the signatures on their own phone.
import { useEffect, useState } from "react";
import { getJSON, type Proof } from "../api";
import { RULE_TEXT, TagPair, VerifyPanel } from "../components/Evidence";

// The server key this page trusts. A build for the demo bakes it in
// (VITE_SERVER_PUB, base64url); otherwise the page says where the key came from.
const BAKED_SERVER_PUB: string | undefined = import.meta.env.VITE_SERVER_PUB;

export function ProofPage({ caseId }: { caseId: number }) {
  const [proof, setProof] = useState<Proof | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getJSON<Proof>(`/v1/proof/${caseId}`).then(setProof).catch((e) => setError(String(e)));
  }, [caseId]);

  if (error) return <p className="p-6 text-lg text-rose-300">This proof isn't available: {error}</p>;
  if (!proof) return <p className="p-6 text-lg text-slate-300">Loading proof…</p>;
  const text = RULE_TEXT[proof.rule] ?? { title: proof.rule, why: "" };
  const accept = proof.rule === "MERCHANT_KNEW" ? proof.log_entries.find((e) => e.fields.kind === "ACCEPT") : undefined;
  const serverPub = BAKED_SERVER_PUB ?? proof.server_pub;

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
      />
      <p className="text-base text-slate-300">
        Both payments carry the same phone's signature, and the bank's server certified that phone's key for this
        wallet. Two signatures on the same money can't both be honest, so this proves the double spend without
        trusting StormCash: your browser checked every signature itself.
      </p>
      <p className="text-xs text-slate-500">
        {BAKED_SERVER_PUB ? "Server key built into this page." : "Server key as reported by this server."} Checks
        use WebCrypto ECDSA P-256 / SHA-256 over the exact signed text.
      </p>
    </main>
  );
}
