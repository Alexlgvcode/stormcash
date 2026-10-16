// Server API client (§12). JSON bodies, byte fields base64url, writes signed with X-SC-Sig.
import { bytesToHex } from '@noble/hashes/utils.js';
import { sha256 } from '@noble/hashes/sha2.js';
import {
  canonical, digestOf, fromWire, hexToB64u, int, itemBodyFromWire, itemBodyToWire, signDigest, str,
  type Cert, type ItemBody, type ItemKind, type MCert, type Policy, type Rcpt,
} from './protocol';
import { deviceKey } from './keys';
import { getApiBase } from './settings';
import type { PathHop } from './store/items';

const TIMEOUT_MS = 8000;

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function request<T>(method: 'GET' | 'POST', path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  const text = body === undefined ? '' : JSON.stringify(body);
  if (method === 'POST') {
    const { priv, pub } = deviceKey();
    const ts = Math.floor(Date.now() / 1000);
    const bodyHash = bytesToHex(sha256(new TextEncoder().encode(text)));
    const d = digestOf(canonical('API', [str(path), bodyHash, int(ts)]));
    headers['X-SC-Pub'] = hexToB64u(pub);
    headers['X-SC-Ts'] = String(ts);
    headers['X-SC-Sig'] = hexToB64u(signDigest(d, priv));
  }
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(getApiBase() + path, {
      method, headers, body: method === 'POST' ? text : undefined, signal: ctl.signal,
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok) throw new ApiError(res.status, (json as { detail?: string }).detail ?? res.statusText);
    return json as T;
  } finally {
    clearTimeout(timer);
  }
}

type Json = Record<string, unknown>;

export async function registerResident(displayName: string, regionId: string): Promise<{ residentId: string; cert: Cert }> {
  const r = await request<{ resident_id: string; cert: Json }>('POST', '/v1/residents/register', {
    display_name: displayName, holder_pub: hexToB64u(deviceKey().pub), region_id: regionId,
  });
  return { residentId: r.resident_id, cert: fromWire<Cert>('CERT', r.cert) };
}

export async function registerMerchant(
  displayName: string, regionId: string, x: number, y: number,
): Promise<{ merchantId: string; mcert: MCert }> {
  const r = await request<{ merchant_id: string; mcert: Json }>('POST', '/v1/merchants/register', {
    display_name: displayName, merchant_pub: hexToB64u(deviceKey().pub), region_id: regionId, x, y,
  });
  return { merchantId: r.merchant_id, mcert: fromWire<MCert>('MCERT', r.mcert) };
}

export async function stormMode(certIdHex: string, capCents: number): Promise<Cert> {
  const r = await request<{ cert: Json }>('POST', '/v1/storm-mode', { cert_id: hexToB64u(certIdHex), cap_cents: capCents });
  return fromWire<Cert>('CERT', r.cert);
}

export async function fetchPolicy(since = 0): Promise<Policy | null> {
  const r = await request<{ policy: Json | null }>('GET', `/v1/policy?since=${since}`);
  return r.policy ? fromWire<Policy>('POLICY', r.policy) : null;
}

export interface UploadItem { kind: ItemKind; body: ItemBody; path: PathHop[] }

export async function sync(items: UploadItem[]): Promise<{ rcpt: Rcpt | null; policy: Policy | null; certs: Cert[] }> {
  const r = await request<{ rcpt: Json | null; policy: Json | null; certs: Json[] }>('POST', '/v1/sync', {
    device_pub: hexToB64u(deviceKey().pub),
    items: items.map((i) => ({ kind: i.kind, body: itemBodyToWire(i.kind, i.body), path: i.path })),
  });
  return {
    rcpt: r.rcpt ? fromWire<Rcpt>('RCPT', r.rcpt) : null,
    policy: r.policy ? fromWire<Policy>('POLICY', r.policy) : null,
    certs: (r.certs ?? []).map((c) => itemBodyFromWire('CERT', c) as Cert),
  };
}
