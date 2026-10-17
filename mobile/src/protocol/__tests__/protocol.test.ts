// Self-consistency tests for the TypeScript protocol twin. Cross-language parity lives in vectors.test.ts.
import { describe, expect, it } from 'vitest';
import { p256 } from '@noble/curves/nist.js';
import {
  b64uToHex,
  canonicalOf,
  derToRaw,
  detailsHash,
  digest,
  equivocation,
  fromWire,
  genesis,
  hexToB64u,
  merchantCheck,
  normalizeLowS,
  payFromWire,
  payToWire,
  publicKeyOf,
  signDigest,
  signObject,
  tagHash,
  toWire,
  verifyDigest,
  type Cert,
  type Det,
  type MCert,
  type Pay,
  type Req,
  type Tag,
} from '..';

const SERVER = '11'.repeat(32);
const MAYA = '22'.repeat(32);
const PHARM = '33'.repeat(32);
const GAS = '44'.repeat(32);
const serverPub = publicKeyOf(SERVER);
const mayaPub = publicKeyOf(MAYA);
const pharmPub = publicKeyOf(PHARM);
const gasPub = publicKeyOf(GAS);
const NOW = 1760000000;
const CERT_ID = 'ab'.repeat(16);

const cert = signObject<Cert>('CERT', {
  cert_id: CERT_ID, cert_ver: 2, holder_pub: mayaPub, cap_cents: 5000,
  issued_at: NOW - 100, expires_at: NOW + 72 * 3600, escrow_ref: 'escrow-1',
}, SERVER);

function makeTag(counter: number, prev: string, amount: number, cum: number, det: Det): Tag {
  return signObject<Tag>('TAG', {
    cert_id: CERT_ID, counter, prev_hash: prev, amount_cents: amount, cum_cents: cum,
    details_hash: detailsHash(det),
  }, MAYA);
}

function pay(merchantPub: string, nonce: string, counter: number, prev: string, amount: number, cum: number): Pay {
  const d: Det = { merchant_pub: merchantPub, nonce, ts: NOW };
  return { c: cert, t: makeTag(counter, prev, amount, cum, d), d };
}

describe('encoding', () => {
  it('renders canonical strings with sorted lists', () => {
    const s = canonicalOf('POLICY', {
      policy_ver: 3, issued_at: 0, frozen_certs: ['ff'.repeat(16), '00'.repeat(16)],
      merchant_limits: [`${'bb'.repeat(16)}:100`, `${'aa'.repeat(16)}:50`],
    });
    expect(s).toBe(`SC1|POLICY|3|0|${'00'.repeat(16)},${'ff'.repeat(16)}|${'aa'.repeat(16)}:50,${'bb'.repeat(16)}:100`);
  });

  it('rejects negative ints and reserved characters', () => {
    expect(() => canonicalOf('REQ', { merchant_id: CERT_ID, amount_cents: -1, nonce: CERT_ID, req_expires_at: 0 })).toThrow();
    expect(() => canonicalOf('MCERT', {
      merchant_id: CERT_ID, merchant_ver: 1, merchant_pub: pharmPub, display_name: 'a|b', region_id: 'r', expires_at: 0,
    })).toThrow();
  });

  it('round-trips base64url without padding', () => {
    for (const h of ['', 'ff', 'ffee', 'ffeedd', 'ffeeddcc', mayaPub]) {
      const b = hexToB64u(h);
      expect(b).not.toContain('=');
      expect(b64uToHex(b)).toBe(h);
    }
  });

  it('round-trips objects over the wire', () => {
    const p = pay(pharmPub, 'cd'.repeat(16), 1, genesis(CERT_ID), 1200, 1200);
    const json = JSON.parse(JSON.stringify(payToWire(p)));
    expect(payFromWire(json)).toEqual(p);
    expect(fromWire<Cert>('CERT', toWire('CERT', cert))).toEqual(cert);
  });
});

describe('crypto', () => {
  it('signs low-S and verifies', () => {
    const d = digest('CERT', cert);
    const sig = signDigest(d, SERVER);
    expect(BigInt('0x' + sig.slice(64)) <= p256.Point.CURVE().n / 2n).toBe(true);
    expect(verifyDigest(sig, d, serverPub)).toBe(true);
    expect(verifyDigest(sig, d, mayaPub)).toBe(false);
  });

  it('accepts high-S signatures', () => {
    const d = digest('CERT', cert);
    const sig = signDigest(d, SERVER);
    const n = p256.Point.CURVE().n;
    const highS = sig.slice(0, 64) + (n - BigInt('0x' + sig.slice(64))).toString(16).padStart(64, '0');
    expect(verifyDigest(highS, d, serverPub)).toBe(true);
  });

  it('converts DER to raw low-S', () => {
    const d = digest('CERT', cert);
    const der = Buffer.from(
      p256.sign(Buffer.from(d, 'hex'), Buffer.from(SERVER, 'hex'), { prehash: false, format: 'der' }),
    ).toString('hex');
    expect(normalizeLowS(derToRaw(der))).toBe(signDigest(d, SERVER));
  });
});

describe('equivocation rules', () => {
  const p1 = pay(pharmPub, '01'.repeat(16), 1, genesis(CERT_ID), 1200, 1200);
  const p2 = pay(pharmPub, '02'.repeat(16), 2, tagHash(p1.t), 500, 1700);
  const p3 = pay(pharmPub, '03'.repeat(16), 3, tagHash(p2.t), 300, 2000);

  it('a valid 3-tag chain fires nothing', () => {
    expect(equivocation(p1.t, p2.t)).toBeNull();
    expect(equivocation(p2.t, p3.t)).toBeNull();
    expect(equivocation(p1.t, p3.t)).toBeNull();
  });

  it('R1 same counter (judge mode: reuse the money)', () => {
    const reuse = pay(gasPub, '09'.repeat(16), 2, tagHash(p1.t), 800, 2000);
    expect(equivocation(p2.t, reuse.t)).toBe('SAME_COUNTER');
  });

  it('R2/R3 when the counter is skipped (judge mode: be clever)', () => {
    const clever = pay(gasPub, '09'.repeat(16), 3, tagHash(p1.t), 800, 2000);
    expect(equivocation(p2.t, clever.t)).toBe('BROKEN_LINK');
    expect(equivocation(p1.t, pay(gasPub, '0a'.repeat(16), 3, 'ee'.repeat(32), 100, 1250).t)).toBe('TOTAL_BACKWARDS');
  });
});

describe('merchant check (judge mode)', () => {
  const nonce = '05'.repeat(16);
  const mc = signObject<MCert>('MCERT', {
    merchant_id: 'aa'.repeat(16), merchant_ver: 1, merchant_pub: gasPub, display_name: 'Gas Station',
    region_id: 'asheville-downtown', expires_at: NOW + 86400,
  }, SERVER);
  const req: Req = { merchant_id: mc.merchant_id, amount_cents: 800, nonce, req_expires_at: NOW + 120 };
  const p1 = pay(pharmPub, '01'.repeat(16), 1, genesis(CERT_ID), 1200, 1200);
  const check = (p: Pay, stored: Tag[]) =>
    merchantCheck(p, { serverPub, merchant: mc, req, policy: null, storedTags: stored, now: NOW });

  it('accepts a fresh payment', () => {
    expect(check(pay(gasPub, nonce, 1, genesis(CERT_ID), 800, 800), [])).toEqual({ ok: true });
  });
  it('reuse the money → SAME_COUNTER, naming the stored tag', () => {
    const r = check(pay(gasPub, nonce, 1, genesis(CERT_ID), 800, 800), [p1.t]);
    expect(r).toMatchObject({ ok: false, check: 'C6', reason: 'SAME_COUNTER', rule: 'SAME_COUNTER' });
    expect(!r.ok && r.conflict && tagHash(r.conflict)).toBe(tagHash(p1.t));
  });
  it('be clever → BROKEN_LINK', () => {
    const r = check(pay(gasPub, nonce, 2, genesis(CERT_ID), 800, 800), [p1.t]);
    expect(r).toMatchObject({ ok: false, check: 'C6', rule: 'BROKEN_LINK' });
  });
  it('a replayed payment → COUNTER_NOT_NEW', () => {
    const again = pay(gasPub, nonce, 1, genesis(CERT_ID), 800, 800);
    expect(check(again, [again.t])).toMatchObject({ ok: false, check: 'C6', reason: 'COUNTER_NOT_NEW' });
  });
});
