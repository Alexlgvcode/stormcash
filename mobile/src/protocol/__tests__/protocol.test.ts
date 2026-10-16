// Self-consistency tests for the TypeScript protocol twin. Cross-language parity lives in vectors.test.ts.
import { describe, expect, it } from 'vitest';
import { p256 } from '@noble/curves/nist.js';
import {
  b64uToHex,
  canonicalOf,
  checkDlogChain,
  contactId,
  derToRaw,
  detailsHash,
  digest,
  dlogGenesis,
  dlogHash,
  equivocation,
  fromWire,
  genesis,
  hexToB64u,
  id8,
  merchantChecks,
  merchantKnew,
  payFromWire,
  payToWire,
  publicKeyOf,
  signDigest,
  signDlog,
  signObject,
  tagHash,
  toWire,
  verifyDigest,
  type Cert,
  type Det,
  type Dlog,
  type MerchantContext,
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
      merchant_limits: ['bb:100', 'aa:50'],
    });
    expect(s).toBe(`SC1|POLICY|3|0|${'00'.repeat(16)},${'ff'.repeat(16)}|aa:50,bb:100`);
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
    expect(derToRaw(der)).toBe(signDigest(d, SERVER));
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

describe('merchant checks C1–C6', () => {
  const nonce = '05'.repeat(16);
  const req: Req = { merchant_id: 'aa'.repeat(16), amount_cents: 1200, nonce, req_expires_at: NOW + 120 };
  const ctx = (over: Partial<MerchantContext> = {}): MerchantContext => ({
    serverPub, now: NOW, merchantPub: pharmPub, merchantId: req.merchant_id, openRequest: req,
    policy: null, storedTags: [], ...over,
  });
  const good = pay(pharmPub, nonce, 1, genesis(CERT_ID), 1200, 1200);

  it('accepts a good payment', () => {
    expect(merchantChecks(good, ctx())).toEqual({ ok: true });
  });
  it('C1 rejects a cert not signed by the server', () => {
    const forged = { ...good, c: signObject<Cert>('CERT', { ...cert, sig: undefined }, MAYA) };
    expect(merchantChecks(forged, ctx())).toMatchObject({ ok: false, check: 'C1' });
  });
  it('C2 rejects expired and frozen certs', () => {
    expect(merchantChecks(good, ctx({ now: cert.expires_at + 601 }))).toMatchObject({ check: 'C2' });
    expect(merchantChecks(good, ctx({
      policy: { policy_ver: 1, issued_at: NOW, frozen_certs: [CERT_ID], merchant_limits: [] },
    }))).toMatchObject({ check: 'C2', reason: 'Certificate frozen' });
  });
  it('C3 rejects a tag signed by someone else', () => {
    const bad = { ...good, t: signObject<Tag>('TAG', { ...good.t, sig: undefined }, GAS) };
    expect(merchantChecks(bad, ctx())).toMatchObject({ check: 'C3' });
  });
  it('C4 rejects a payment for another merchant or request', () => {
    expect(merchantChecks(good, ctx({ merchantPub: gasPub }))).toMatchObject({ check: 'C4' });
    expect(merchantChecks(good, ctx({ openRequest: { ...req, nonce: '06'.repeat(16) } }))).toMatchObject({ check: 'C4' });
  });
  it('C5 rejects over cap and over the shop limit', () => {
    const big = pay(pharmPub, nonce, 1, genesis(CERT_ID), 6000, 6000);
    expect(merchantChecks(big, ctx({ openRequest: { ...req, amount_cents: 6000 } }))).toMatchObject({ check: 'C5' });
    expect(merchantChecks(good, ctx({
      policy: { policy_ver: 1, issued_at: NOW, frozen_certs: [], merchant_limits: [`${req.merchant_id}:1000`] },
    }))).toMatchObject({ check: 'C5', reason: "Over this shop's limit" });
  });
  it('C6 refuses a rolled-back wallet', () => {
    const atPharmacy = pay(pharmPub, '07'.repeat(16), 1, genesis(CERT_ID), 1200, 1200);
    const r = merchantChecks(good, ctx({ storedTags: [atPharmacy.t] }));
    expect(r).toMatchObject({ ok: false, check: 'C6', rule: 'SAME_COUNTER' });
  });
});

describe('device logs', () => {
  function entry(seq: number, prev: string, ts: number, body: Partial<Dlog>): Dlog {
    return signDlog({ device_pub: pharmPub, seq, prev_hash: prev, ts, ...body } as Dlog, PHARM);
  }
  const e1 = entry(1, dlogGenesis(pharmPub), NOW, { kind: 'ACCEPT', tag_hash: 'aa'.repeat(32), cert_id: CERT_ID, held_ids: [] });
  const e2 = entry(2, dlogHash(e1), NOW + 1, {
    kind: 'CONTACT', contact_id: 'bb'.repeat(32), peer_pub: mayaPub, sent_ids: ['cc'.repeat(8)], recv_ids: [],
    sent_overflow: 0, recv_overflow: 0,
  });
  const e3 = entry(3, dlogHash(e2), NOW + 2, { kind: 'REFUSE', tag_hash: 'dd'.repeat(32), cert_id: CERT_ID, check: 'C6' });

  it('a clean chain passes R6', () => {
    expect(checkDlogChain([e3, e1, e2])).toEqual({ ok: true });
  });
  it('detects forks and broken links', () => {
    const fork = entry(2, dlogHash(e1), NOW + 5, { kind: 'REFUSE', tag_hash: 'ee'.repeat(32), cert_id: CERT_ID, check: 'C1' });
    expect(checkDlogChain([e1, e2, fork])).toMatchObject({ ok: false, reason: 'FORK' });
    const broken = entry(3, 'ff'.repeat(32), NOW + 2, { kind: 'REFUSE', tag_hash: 'dd'.repeat(32), cert_id: CERT_ID, check: 'C6' });
    expect(checkDlogChain([e1, e2, broken])).toMatchObject({ ok: false, reason: 'BROKEN_LINK' });
  });
  it('both sides compute the same contact id', () => {
    const n1 = '01'.repeat(16), n2 = '02'.repeat(16);
    expect(contactId(mayaPub, n1, gasPub, n2)).toBe(contactId(gasPub, n2, mayaPub, n1));
  });
});

describe('R5 merchant knew', () => {
  const x = pay(pharmPub, '01'.repeat(16), 1, genesis(CERT_ID), 1200, 1200).t; // first spend
  const z = pay(gasPub, '02'.repeat(16), 1, genesis(CERT_ID), 1500, 1500).t; // rolled-back spend
  const cid = contactId(mayaPub, '0a'.repeat(16), gasPub, '0b'.repeat(16));
  const contact = (device: string, priv: string, peer: string, sent: string[], recv: string[]) =>
    signDlog({
      device_pub: device, seq: 1, prev_hash: dlogGenesis(device), ts: NOW - 60, kind: 'CONTACT',
      contact_id: cid, peer_pub: peer, sent_ids: sent, recv_ids: recv, sent_overflow: 0, recv_overflow: 0,
    }, priv);
  const base = { accepted: z, merchantPub: gasPub, acceptTs: NOW, otherTags: [x] };

  it('(a) fires via held_ids', () => {
    const accept = signDlog({
      device_pub: gasPub, seq: 2, prev_hash: 'aa'.repeat(32), ts: NOW, kind: 'ACCEPT',
      tag_hash: tagHash(z), cert_id: CERT_ID, held_ids: [tagHash(x)],
    }, GAS);
    expect(merchantKnew({ ...base, acceptEntry: accept, contacts: [] })).toEqual(x);
  });
  it('(b) fires via a paired contact', () => {
    const maya = contact(mayaPub, MAYA, gasPub, [id8(tagHash(x))], []);
    const gas = contact(gasPub, GAS, mayaPub, [], []);
    expect(merchantKnew({ ...base, acceptEntry: null, contacts: [maya, gas] })).toEqual(x);
  });
  it('(c) a one-sided contact does not fire', () => {
    const maya = contact(mayaPub, MAYA, gasPub, [id8(tagHash(x))], []);
    expect(merchantKnew({ ...base, acceptEntry: null, contacts: [maya] })).toBeNull();
  });
});
