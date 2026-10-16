// "Verify it yourself" (spec §18.3, §18.6): everything here runs in the
// viewer's browser with WebCrypto. It rebuilds each signed string from the
// displayed fields with the §7.2 rules (so the server can't show one thing and
// sign another), checks the signature against the holder's or merchant's key,
// and re-checks the broken rule from the fields. No server is trusted.

const enc = new TextEncoder();

export type Fields = Record<string, string | number | string[]>;

// Bytes ----------------------------------------------------------------------------

export function hexToBytes(hex: string): Uint8Array {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.slice(2 * i, 2 * i + 2), 16);
  return out;
}

export function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function b64uToBytes(s: string): Uint8Array {
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (s.length % 4)) % 4);
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
}

export async function sha256Hex(text: string): Promise<string> {
  return bytesToHex(new Uint8Array(await crypto.subtle.digest("SHA-256", enc.encode(text))));
}

// Canonical strings (§7.2, §7.4, §9.2) ---------------------------------------------------

const sortedHex = (list: string[]) => [...list].sort().join(",");
const str = (s: string) => s.normalize("NFC");

const LAYOUTS: Record<string, (f: Fields) => (string | number)[]> = {
  TAG: (f) => [f.cert_id as string, f.counter as number, f.prev_hash as string, f.amount_cents as number,
    f.cum_cents as number, f.details_hash as string],
  CERT: (f) => [f.cert_id as string, f.cert_ver as number, f.holder_pub as string, f.cap_cents as number,
    f.issued_at as number, f.expires_at as number, str(f.escrow_ref as string)],
  DLOG: (f) => {
    const head = [f.device_pub as string, f.seq as number, f.prev_hash as string, f.ts as number, f.kind as string];
    if (f.kind === "ACCEPT") return [...head, f.tag_hash as string, f.cert_id as string, sortedHex(f.held_ids as string[])];
    if (f.kind === "REFUSE") return [...head, f.tag_hash as string, f.cert_id as string, f.check as string];
    return [...head, f.contact_id as string, f.peer_pub as string, sortedHex(f.sent_ids as string[]),
      sortedHex(f.recv_ids as string[]), f.sent_overflow as number, f.recv_overflow as number];
  },
};

export function canonical(type: string, fields: Fields): string {
  const layout = LAYOUTS[type];
  if (!layout) throw new Error(`no canonical layout for ${type}`);
  return ["SC1", type, ...layout(fields).map(String)].join("|");
}

// P-256 public keys: WebCrypto wants uncompressed points, the protocol uses compressed (§7.1).

const P = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffffn;
const B = 0x5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604bn;

function modPow(base: bigint, exp: bigint, mod: bigint): bigint {
  let result = 1n;
  base %= mod;
  while (exp > 0n) {
    if (exp & 1n) result = (result * base) % mod;
    base = (base * base) % mod;
    exp >>= 1n;
  }
  return result;
}

export function decompress(pub: Uint8Array): Uint8Array {
  if (pub.length !== 33 || (pub[0] !== 2 && pub[0] !== 3)) throw new Error("not a compressed P-256 key");
  const x = BigInt("0x" + bytesToHex(pub.slice(1)));
  const rhs = (((x * x * x - 3n * x + B) % P) + P) % P;
  let y = modPow(rhs, (P + 1n) / 4n, P); // P ≡ 3 (mod 4)
  if ((y * y) % P !== rhs) throw new Error("public key is not on the curve");
  if ((y & 1n) !== BigInt(pub[0] & 1)) y = P - y;
  const out = new Uint8Array(65);
  out[0] = 4;
  out.set(pub.slice(1), 1);
  out.set(hexToBytes(y.toString(16).padStart(64, "0")), 33);
  return out;
}

/** ECDSA P-256 / SHA-256 over the UTF-8 canonical string; sig is raw r‖s (64 bytes). */
export async function verifySig(pubHex: string, canonicalString: string, sig: Uint8Array): Promise<boolean> {
  const key = await crypto.subtle.importKey(
    "raw", decompress(hexToBytes(pubHex)) as BufferSource, { name: "ECDSA", namedCurve: "P-256" }, false,
    ["verify"],
  );
  return crypto.subtle.verify({ name: "ECDSA", hash: "SHA-256" }, key, sig as BufferSource,
    enc.encode(canonicalString) as BufferSource);
}

// One signed object -----------------------------------------------------------------------

export interface SignedObject {
  type: string;
  json: Record<string, unknown>; // transport form; carries `sig` in base64url
  fields: Fields;
  canonical: string;
  digest: string;
}

export interface Check {
  label: string;
  ok: boolean;
  detail?: string;
}

/** Rebuild the canonical string from the fields, then check the signature. */
export async function checkSigned(obj: SignedObject, pubHex: string, who: string): Promise<Check[]> {
  const rebuilt = canonical(obj.type, obj.fields);
  const sig = b64uToBytes(String(obj.json.sig ?? ""));
  return [
    { label: `${obj.type}: the signed text matches the fields shown`, ok: rebuilt === obj.canonical },
    { label: `${obj.type}: signature is valid for ${who}`, ok: sig.length === 64 && (await verifySig(pubHex, rebuilt, sig)) },
  ];
}

// The rules (§8.3), recomputed from the fields -----------------------------------------------

export async function ruleHolds(rule: string, a: Fields, b: Fields): Promise<Check> {
  const [lo, hi] = (a.counter as number) <= (b.counter as number) ? [a, b] : [b, a];
  if (a.cert_id !== b.cert_id) return { label: "Both tags spend the same certificate", ok: false };
  if (rule === "SAME_COUNTER") {
    const differ = (await sha256Hex(canonical("TAG", a))) !== (await sha256Hex(canonical("TAG", b)));
    return { label: `Same counter (${a.counter}) on two different payments`, ok: a.counter === b.counter && differ };
  }
  if (rule === "BROKEN_LINK") {
    const loHash = await sha256Hex(canonical("TAG", lo));
    return {
      label: `Counter ${hi.counter} doesn't point back to counter ${lo.counter}`,
      ok: (hi.counter as number) === (lo.counter as number) + 1 && hi.prev_hash !== loHash,
      detail: `expected prev_hash ${loHash.slice(0, 16)}…, signed ${String(hi.prev_hash).slice(0, 16)}…`,
    };
  }
  if (rule === "TOTAL_BACKWARDS") {
    const before = (hi.cum_cents as number) - (hi.amount_cents as number);
    return {
      label: `Running total went backwards: ${before} < ${lo.cum_cents} cents`,
      ok: (hi.counter as number) > (lo.counter as number) && before < (lo.cum_cents as number),
    };
  }
  return { label: `Unknown rule ${rule}`, ok: false };
}

/** Which TAG fields to paint red for a rule (§18.3: "the field that conflicts in red"). */
export function conflictingFields(rule: string): { a: string[]; b: string[] } {
  if (rule === "SAME_COUNTER") return { a: ["counter"], b: ["counter"] };
  if (rule === "BROKEN_LINK") return { a: [], b: ["prev_hash"] };
  if (rule === "TOTAL_BACKWARDS") return { a: ["cum_cents"], b: ["cum_cents", "amount_cents"] };
  return { a: [], b: [] };
}
