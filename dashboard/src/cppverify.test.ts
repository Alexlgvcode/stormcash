// The C++ verifier as the proof page runs it (the committed WebAssembly build,
// src/wasm/), on GET /v1/proof responses captured from the real server
// (cpp/verify/tests/fixtures/) and on tampered copies, next to the WebCrypto
// check (runChecks in verify.ts). The two must agree on every one.
// Run: npm test.
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";
import { agreement, checkWithCpp, type CppVerdict } from "./cppverify.ts";
import { runChecks, type SignedObject } from "./verify.ts";

const wasm = readFileSync(new URL("./wasm/stormcash_verify.wasm", import.meta.url));
// Node can't fetch the .wasm next to the module the way a browser does.
const options = {
  instantiateWasm(imports: WebAssembly.Imports, done: (instance: WebAssembly.Instance) => void) {
    WebAssembly.instantiate(wasm, imports).then((r) => done(r.instance));
    return {};
  },
};

const fixturesDir = new URL("../../cpp/verify/tests/fixtures/", import.meta.url);

interface ProofDoc {
  rule: string;
  server_pub: string;
  cert: SignedObject;
  tag_a: SignedObject;
  tag_b: SignedObject;
  log_entries: SignedObject[];
  [key: string]: unknown;
}

function fixture(name: string): ProofDoc {
  return JSON.parse(readFileSync(new URL(`proof_${name}.json`, fixturesDir), "utf8"));
}

/** Both checks, as ProofPage runs them, with the server key pinned. */
async function both(proof: ProofDoc, serverPub = proof.server_pub): Promise<{ web: boolean; cpp: CppVerdict }> {
  const accept = proof.rule === "MERCHANT_KNEW" ? proof.log_entries.find((e) => e.fields.kind === "ACCEPT") : undefined;
  const checks = await runChecks({
    rule: proof.rule, cert: proof.cert, tagA: proof.tag_a, tagB: proof.tag_b, serverPubB64: serverPub, accept,
  });
  return { web: checks.every((c) => c.ok), cpp: await checkWithCpp(proof, serverPub, options) };
}

const PROVEN = ["same_counter", "broken_link", "total_backwards", "merchant_knew_held_ids"];

test("every captured proof is in the test", () => {
  const names = readdirSync(fixturesDir).filter((f) => /^proof_.*\.json$/.test(f));
  assert.deepEqual(names.sort(), [...PROVEN, "merchant_knew_paired_contact"].map((n) => `proof_${n}.json`).sort());
});

test("real proofs: both implementations verify them", async () => {
  for (const name of PROVEN) {
    const proof = fixture(name);
    const { web, cpp } = await both(proof);
    assert.equal(web, true, name);
    assert.equal(cpp.status, "proven", `${name}: ${cpp.report ?? cpp.error}`);
    assert.equal(cpp.rule, proof.rule);
    assert.ok(cpp.lines!.length > 0 && cpp.lines!.every((l) => l.ok), name);
    assert.equal(agreement(web, cpp), "both_verified", name);
  }
});

test("the verdict is the CLI's, and says where the key came from", async () => {
  const { cpp } = await both(fixture("same_counter"));
  assert.ok(
    cpp.verdict!.startsWith(
      "SAME_COUNTER: both signatures valid under holder key 02700ac63d3db3d6...; certificate signed by StormCash",
    ),
    cpp.verdict,
  );
  assert.match(cpp.report!, /^Case 1: SAME_COUNTER\n {2}ok {4}CERT: /);
  assert.ok(cpp.lines!.some((l) => l.text.includes("(built into this page)")));
  assert.match(cpp.crypto, /^portable \(p256-m/);

  const unpinned = await checkWithCpp(fixture("same_counter"), "", options);
  assert.equal(unpinned.status, "proven");
  assert.match(unpinned.verdict!, /not pinned/);
});

test("merchant knew through a paired contact: neither claims the whole case", async () => {
  // /v1/proof has no CONTACT entries, so the C++ side says incomplete and the
  // WebCrypto side fails its held_ids check: they agree it isn't fully shown.
  const { web, cpp } = await both(fixture("merchant_knew_paired_contact"));
  assert.equal(cpp.status, "incomplete");
  assert.equal(web, false);
  assert.equal(agreement(web, cpp), "neither_verified");
});

test("tampered proofs: both implementations reject them", async () => {
  const cases: [string, (p: ProofDoc) => string | void][] = [
    ["payment B's amount changed where it is signed and shown", (p) => {
      p.tag_b.json.amt = 1;
      p.tag_b.fields.amount_cents = 1;
    }],
    ["payment B's amount changed only where it is shown", (p) => {
      p.tag_b.fields.amount_cents = 1;
    }],
    ["payment A's signature swapped for payment B's", (p) => {
      p.tag_a.json.sig = p.tag_b.json.sig;
    }],
    ["the certificate checked against the wrong server key", (p) => p.holder_pub as string],
  ];
  for (const [what, tamper] of cases) {
    const proof = fixture("same_counter");
    const pin = tamper(proof) ?? proof.server_pub;
    const { web, cpp } = await both(proof, pin);
    assert.equal(web, false, what);
    assert.equal(cpp.status, "invalid", `${what}: ${cpp.report ?? cpp.error}`);
    assert.ok(cpp.verdict!.startsWith("NOT VERIFIED: "), what);
    assert.equal(agreement(web, cpp), "neither_verified", what);
  }
});

test("a file that isn't a proof is an error, not a verdict", async () => {
  const cpp = await checkWithCpp({ case_id: 1 }, "", options);
  assert.equal(cpp.status, "error");
  assert.match(cpp.error!, /not a \/v1\/proof document/);
  assert.equal(agreement(true, cpp), "cpp_unavailable");
});

test("agreement", () => {
  const v = (status: CppVerdict["status"]): CppVerdict => ({ status, crypto: "" });
  assert.equal(agreement(true, v("proven")), "both_verified");
  assert.equal(agreement(false, v("invalid")), "neither_verified");
  assert.equal(agreement(false, v("incomplete")), "neither_verified");
  assert.equal(agreement(true, v("invalid")), "disagree");
  assert.equal(agreement(true, v("incomplete")), "disagree");
  assert.equal(agreement(false, v("proven")), "disagree");
  assert.equal(agreement(true, null), "cpp_unavailable");
  assert.equal(agreement(false, v("error")), "cpp_unavailable");
});
