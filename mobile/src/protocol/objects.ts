// Protocol objects (§7.4, §9.2, §10.2): canonical field order, hashes, signing, JSON codec.
// Inside the app every byte field is a lowercase hex string; JSON on the wire uses base64url.
import {
  b64uToHex,
  bytes,
  bytesList,
  canonical,
  digestOf,
  enumToken,
  hexToB64u,
  int,
  str,
  strList,
  type Hex,
} from './encoding';
import { signDigest, verifyDigest } from './crypto';

type Kind =
  | 'int'
  | 'str'
  | 'enum'
  | 'strlist'
  | { b: number }
  | { blist: number };

type Field = readonly [name: string, key: string, kind: Kind];

const B8 = { b: 8 } as const;
const B16 = { b: 16 } as const;
const B32 = { b: 32 } as const;
const B33 = { b: 33 } as const;

export const SCHEMAS = {
  CERT: [
    ['cert_id', 'ci', B16],
    ['cert_ver', 'cv', 'int'],
    ['holder_pub', 'hp', B33],
    ['cap_cents', 'cap', 'int'],
    ['issued_at', 'ia', 'int'],
    ['expires_at', 'ea', 'int'],
    ['escrow_ref', 'er', 'str'],
  ],
  MCERT: [
    ['merchant_id', 'mi', B16],
    ['merchant_ver', 'mv', 'int'],
    ['merchant_pub', 'mp', B33],
    ['display_name', 'dn', 'str'],
    ['region_id', 'rg', 'str'],
    ['expires_at', 'ea', 'int'],
  ],
  REQ: [
    ['merchant_id', 'mi', B16],
    ['amount_cents', 'amt', 'int'],
    ['nonce', 'n', B16],
    ['req_expires_at', 'rx', 'int'],
  ],
  DET: [
    ['merchant_pub', 'mp', B33],
    ['nonce', 'n', B16],
    ['ts', 'ts', 'int'],
  ],
  TAG: [
    ['cert_id', 'ci', B16],
    ['counter', 'k', 'int'],
    ['prev_hash', 'ph', B32],
    ['amount_cents', 'amt', 'int'],
    ['cum_cents', 'cum', 'int'],
    ['details_hash', 'dh', B32],
  ],
  POLICY: [
    ['policy_ver', 'pv', 'int'],
    ['issued_at', 'ia', 'int'],
    ['frozen_certs', 'fc', { blist: 16 }],
    ['merchant_limits', 'ml', 'strlist'],
  ],
  RENEW: [
    ['cert_id', 'ci', B16],
    ['chain_head', 'ch', B32],
    ['counter', 'k', 'int'],
    ['ts', 'ts', 'int'],
  ],
  RCPT: [
    ['ts', 'ts', 'int'],
    ['item_ids', 'ids', { blist: 32 }],
  ],
} as const satisfies Record<string, readonly Field[]>;

const DLOG_HEAD: readonly Field[] = [
  ['device_pub', 'dp', B33],
  ['seq', 'q', 'int'],
  ['prev_hash', 'ph', B32],
  ['ts', 'ts', 'int'],
  ['kind', 'kd', 'enum'],
];

const DLOG_BODIES: Record<DlogKind, readonly Field[]> = {
  ACCEPT: [
    ['tag_hash', 'th', B32],
    ['cert_id', 'ci', B16],
    ['held_ids', 'hi', { blist: 32 }],
  ],
  REFUSE: [
    ['tag_hash', 'th', B32],
    ['cert_id', 'ci', B16],
    ['check', 'ck', 'enum'],
  ],
  CONTACT: [
    ['contact_id', 'cid', B32],
    ['peer_pub', 'pp', B33],
    ['sent_ids', 'si', { blist: 8 }],
    ['recv_ids', 'ri', { blist: 8 }],
    ['sent_overflow', 'so', 'int'],
    ['recv_overflow', 'ro', 'int'],
  ],
};

// ---- Types ----

export interface Cert {
  cert_id: Hex; cert_ver: number; holder_pub: Hex; cap_cents: number;
  issued_at: number; expires_at: number; escrow_ref: string; sig?: Hex;
}
export interface MCert {
  merchant_id: Hex; merchant_ver: number; merchant_pub: Hex; display_name: string;
  region_id: string; expires_at: number; sig?: Hex;
}
export interface Req { merchant_id: Hex; amount_cents: number; nonce: Hex; req_expires_at: number; sig?: Hex }
export interface Det { merchant_pub: Hex; nonce: Hex; ts: number }
export interface Tag {
  cert_id: Hex; counter: number; prev_hash: Hex; amount_cents: number;
  cum_cents: number; details_hash: Hex; sig?: Hex;
}
export interface Policy {
  policy_ver: number; issued_at: number; frozen_certs: Hex[]; merchant_limits: string[]; sig?: Hex;
}
export interface Renew { cert_id: Hex; chain_head: Hex; counter: number; ts: number; sig?: Hex }
export interface Rcpt { ts: number; item_ids: Hex[]; sig?: Hex }
export interface Pay { c: Cert; t: Tag; d: Det }
export interface PaymentRequest { mc: MCert; rq: Req }
export type EquivocationRule = 'SAME_COUNTER' | 'BROKEN_LINK' | 'TOTAL_BACKWARDS';
export interface Proof { a: Tag; b: Tag; rule: EquivocationRule }

export type DlogKind = 'ACCEPT' | 'REFUSE' | 'CONTACT';
export type CheckId = 'C1' | 'C2' | 'C3' | 'C4' | 'C5' | 'C6';
interface DlogHead { device_pub: Hex; seq: number; prev_hash: Hex; ts: number; sig?: Hex }
export type Dlog =
  | (DlogHead & { kind: 'ACCEPT'; tag_hash: Hex; cert_id: Hex; held_ids: Hex[] })
  | (DlogHead & { kind: 'REFUSE'; tag_hash: Hex; cert_id: Hex; check: CheckId })
  | (DlogHead & {
      kind: 'CONTACT'; contact_id: Hex; peer_pub: Hex; sent_ids: Hex[]; recv_ids: Hex[];
      sent_overflow: number; recv_overflow: number;
    });

export type SchemaType = keyof typeof SCHEMAS;

// ---- Canonical strings and digests ----

function render(kind: Kind, v: unknown): string {
  if (kind === 'int') return int(v as number);
  if (kind === 'str') return str(v as string);
  if (kind === 'enum') return enumToken(v as string);
  if (kind === 'strlist') return strList(v as string[]);
  if ('b' in kind) return bytes(v as Hex, kind.b);
  return bytesList(v as Hex[], kind.blist);
}

function renderFields(fields: readonly Field[], obj: Record<string, unknown>): string[] {
  return fields.map(([name, , kind]) => {
    if (!(name in obj)) throw new Error(`missing field ${name}`);
    return render(kind, obj[name]);
  });
}

function dlogFields(e: Dlog): readonly Field[] {
  const body = DLOG_BODIES[e.kind];
  if (!body) throw new Error(`unknown DLOG kind ${e.kind}`);
  return [...DLOG_HEAD, ...body];
}

export function canonicalOf(type: SchemaType, obj: object): string;
export function canonicalOf(type: 'DLOG', obj: Dlog): string;
export function canonicalOf(type: SchemaType | 'DLOG', obj: object): string {
  const fields = type === 'DLOG' ? dlogFields(obj as Dlog) : SCHEMAS[type];
  return canonical(type, renderFields(fields, obj as Record<string, unknown>));
}

export const digest = (type: SchemaType, obj: object): Hex => digestOf(canonicalOf(type, obj));
export const dlogHash = (e: Dlog): Hex => digestOf(canonicalOf('DLOG', e));

export const tagHash = (t: Tag): Hex => digest('TAG', t);
export const detailsHash = (d: Det): Hex => digest('DET', d);
export const genesis = (certId: Hex): Hex => digestOf(canonical('GEN', [bytes(certId, 16)]));
export const dlogGenesis = (devicePub: Hex): Hex => digestOf(canonical('DGEN', [bytes(devicePub, 33)]));

/** Both sides of a sync session compute the same id (§9.2). */
export function contactId(pubA: Hex, nonceA: Hex, pubB: Hex, nonceB: Hex): Hex {
  const [lo, hi] = pubA < pubB ? [[pubA, nonceA], [pubB, nonceB]] : [[pubB, nonceB], [pubA, nonceA]];
  return digestOf(
    canonical('CONTACT', [bytes(lo[0], 33), bytes(hi[0], 33), bytes(lo[1], 16), bytes(hi[1], 16)]),
  );
}

// ---- Signing ----

export function signObject<T extends object>(type: SchemaType, obj: T, priv: Hex): T & { sig: Hex } {
  return { ...obj, sig: signDigest(digest(type, obj), priv) };
}

export function verifyObject(type: SchemaType, obj: { sig?: Hex }, pub: Hex): boolean {
  if (!obj.sig) return false;
  try {
    return verifyDigest(obj.sig, digest(type, obj), pub);
  } catch {
    return false;
  }
}

export function signDlog(e: Dlog, priv: Hex): Dlog {
  return { ...e, sig: signDigest(dlogHash(e), priv) };
}

export function verifyDlog(e: Dlog): boolean {
  if (!e.sig) return false;
  try {
    return verifyDigest(e.sig, dlogHash(e), e.device_pub);
  } catch {
    return false;
  }
}

// ---- JSON transport codec (§7.3) ----

type Json = Record<string, unknown>;

function encodeValue(kind: Kind, v: unknown): unknown {
  if (typeof kind === 'object') {
    return 'b' in kind ? hexToB64u(v as Hex) : (v as Hex[]).map(hexToB64u);
  }
  return v;
}

function decodeValue(kind: Kind, v: unknown): unknown {
  if (typeof kind === 'object') {
    if ('b' in kind) return b64uToHex(v as string);
    if (!Array.isArray(v)) throw new Error('expected list');
    return v.map((x) => b64uToHex(x as string));
  }
  if (kind === 'int' && typeof v !== 'number') throw new Error('expected integer');
  if ((kind === 'str' || kind === 'enum') && typeof v !== 'string') throw new Error('expected string');
  if (kind === 'strlist' && !Array.isArray(v)) throw new Error('expected list');
  return v;
}

function encodeFields(fields: readonly Field[], obj: Json): Json {
  const out: Json = {};
  for (const [name, key, kind] of fields) out[key] = encodeValue(kind, obj[name]);
  if (typeof obj.sig === 'string') out.sig = hexToB64u(obj.sig);
  return out;
}

function decodeFields(fields: readonly Field[], json: Json): Json {
  const out: Json = {};
  for (const [name, key, kind] of fields) {
    if (!(key in json)) throw new Error(`missing key ${key}`);
    out[name] = decodeValue(kind, json[key]);
  }
  if (typeof json.sig === 'string') out.sig = b64uToHex(json.sig);
  return out;
}

export function toWire(type: SchemaType, obj: object): Json {
  return encodeFields(SCHEMAS[type], obj as Json);
}

export function fromWire<T>(type: SchemaType, json: Json): T {
  return decodeFields(SCHEMAS[type], json) as T;
}

export function dlogToWire(e: Dlog): Json {
  return encodeFields(dlogFields(e), e as unknown as Json);
}

export function dlogFromWire(json: Json): Dlog {
  const kind = json.kd as DlogKind;
  const fields = dlogFields({ kind } as Dlog);
  return decodeFields(fields, json) as unknown as Dlog;
}

export const payToWire = (p: Pay): Json => ({
  c: toWire('CERT', p.c), t: toWire('TAG', p.t), d: toWire('DET', p.d),
});
export const payFromWire = (j: Json): Pay => ({
  c: fromWire<Cert>('CERT', j.c as Json),
  t: fromWire<Tag>('TAG', j.t as Json),
  d: fromWire<Det>('DET', j.d as Json),
});

export const requestToWire = (r: PaymentRequest): Json => ({
  mc: toWire('MCERT', r.mc), rq: toWire('REQ', r.rq),
});
export const requestFromWire = (j: Json): PaymentRequest => ({
  mc: fromWire<MCert>('MCERT', j.mc as Json),
  rq: fromWire<Req>('REQ', j.rq as Json),
});

export const proofToWire = (p: Proof): Json => ({
  a: toWire('TAG', p.a), b: toWire('TAG', p.b), rule: p.rule,
});
export const proofFromWire = (j: Json): Proof => ({
  a: fromWire<Tag>('TAG', j.a as Json),
  b: fromWire<Tag>('TAG', j.b as Json),
  rule: j.rule as EquivocationRule,
});

// QR payloads: "SC1:" + JSON (§7.3)
export const QR_PREFIX = 'SC1:';
export const toQr = (json: Json): string => QR_PREFIX + JSON.stringify(json);
export function fromQr(s: string): Json {
  if (!s.startsWith(QR_PREFIX)) throw new Error('not a StormCash code');
  return JSON.parse(s.slice(QR_PREFIX.length)) as Json;
}

// ---- Items (§10.2) ----

export type ItemKind = 'PROOF' | 'POLICY' | 'RCPT' | 'CERT' | 'PAY' | 'DLOG' | 'RENEW' | 'TAG';

export const ITEM_PRIORITY: Record<ItemKind, number> = {
  PROOF: 1, POLICY: 2, RCPT: 2, CERT: 2, PAY: 3, DLOG: 3, RENEW: 3, TAG: 4,
};

export type ItemBody = Proof | Policy | Rcpt | Cert | Pay | Dlog | Renew | Tag;

export function itemId(kind: ItemKind, body: ItemBody): Hex {
  switch (kind) {
    case 'PROOF': {
      const p = body as Proof;
      const [x, y] = [tagHash(p.a), tagHash(p.b)].sort();
      return digestOf(canonical('PRF', [x, y]));
    }
    case 'POLICY': return digest('POLICY', body);
    case 'RCPT': return digest('RCPT', body);
    case 'CERT': return digest('CERT', body);
    case 'RENEW': return digest('RENEW', body);
    case 'PAY': return tagHash((body as Pay).t);
    case 'TAG': return tagHash(body as Tag);
    case 'DLOG': return dlogHash(body as Dlog);
  }
}

export const id8 = (id: Hex): Hex => id.slice(0, 16);

export function itemBodyToWire(kind: ItemKind, body: ItemBody): Json {
  switch (kind) {
    case 'PROOF': return proofToWire(body as Proof);
    case 'PAY': return payToWire(body as Pay);
    case 'DLOG': return dlogToWire(body as Dlog);
    default: return toWire(kind, body);
  }
}

export function itemBodyFromWire(kind: ItemKind, json: Json): ItemBody {
  switch (kind) {
    case 'PROOF': return proofFromWire(json);
    case 'PAY': return payFromWire(json);
    case 'DLOG': return dlogFromWire(json);
    case 'POLICY': case 'RCPT': case 'CERT': case 'RENEW': case 'TAG':
      return fromWire(kind, json);
    default: throw new Error(`unknown item kind ${kind as string}`);
  }
}
