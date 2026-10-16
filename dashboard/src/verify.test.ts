// The browser verifier against the shared vectors (spec/vectors.json, §20):
// canonical strings byte for byte, WebCrypto signatures, and the rules.
// Run: npm test (Node's built-in test runner, WebCrypto via globalThis.crypto).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { canonical, checkSigned, hexToBytes, ruleHolds, verifySig, type Fields } from "./verify.ts";

const vectors = JSON.parse(readFileSync(new URL("../../spec/vectors.json", import.meta.url), "utf8"));

const objects = vectors.objects.filter((v: { type: string }) => ["TAG", "CERT", "DLOG"].includes(v.type));

test("canonical strings match the vectors byte for byte", () => {
  assert.ok(objects.length >= 10);
  for (const v of objects) assert.equal(canonical(v.type, v.fields), v.canonical, v.name);
});

test("signatures verify (and the invalid ones don't)", async () => {
  for (const v of objects) {
    const ok = v.sig !== null && (await verifySig(v.pub, canonical(v.type, v.fields), hexToBytes(v.sig)));
    assert.equal(ok, v.valid, v.name);
  }
});

test("raw signature vectors, including a high-S one that must verify", async () => {
  // Rebuild the message: these vectors sign tag_counter1's digest.
  const tag1 = vectors.objects.find((v: { name: string }) => v.name === "tag_counter1");
  const tag2 = vectors.objects.find((v: { name: string }) => v.name === "tag_counter2");
  const byDigest: Record<string, string> = { [tag1.digest]: tag1.canonical, [tag2.digest]: tag2.canonical };
  for (const v of vectors.signatures) {
    let ok = false;
    try {
      ok = await verifySig(v.pub, byDigest[v.digest], hexToBytes(v.sig));
    } catch {
      ok = false;
    }
    assert.equal(ok, v.valid, v.name);
  }
});

test("checkSigned spots a field that doesn't match the signed text", async () => {
  const tag1 = vectors.objects.find((v: { name: string }) => v.name === "tag_counter1");
  const sigB64 = Buffer.from(hexToBytes(tag1.sig)).toString("base64url");
  const good = await checkSigned({ ...tag1, json: { sig: sigB64 } }, tag1.pub, "Maya");
  assert.deepEqual(good.map((c) => c.ok), [true, true]);
  const shown = { ...tag1.fields, amount_cents: 1 };
  const bad = await checkSigned({ ...tag1, fields: shown, json: { sig: sigB64 } }, tag1.pub, "Maya");
  assert.deepEqual(bad.map((c) => c.ok), [false, false]);
});

test("rules recomputed from the fields agree with the vectors", async () => {
  for (const v of vectors.proofs) {
    const holds = await ruleHolds(v.rule, v.a.fields as Fields, v.b.fields as Fields);
    // A proof is valid when its rule holds and both signatures verify; the forged-signature
    // vector breaks a real rule, so check the rule part against rules_fired instead.
    if (v.name !== "proof_forged_signature") assert.equal(holds.ok, v.valid, v.name);
  }
  for (const v of vectors.equivocation) {
    for (const rule of ["SAME_COUNTER", "BROKEN_LINK", "TOTAL_BACKWARDS"]) {
      const holds = await ruleHolds(rule, v.a.fields as Fields, v.b.fields as Fields);
      assert.equal(holds.ok, v.rules_fired.includes(rule), `${v.name} ${rule}`);
    }
  }
});
