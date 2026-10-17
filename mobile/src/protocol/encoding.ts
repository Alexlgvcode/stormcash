// Canonical encoding (§7.2) and transport byte codecs (§7.3).
// Byte fields are lowercase hex strings everywhere inside the app; base64url only on the wire.
import { sha256 } from '@noble/hashes/sha2.js';
import { bytesToHex, hexToBytes, utf8ToBytes } from '@noble/hashes/utils.js';

export type Hex = string;

const HEX_RE = /^(?:[0-9a-f]{2})*$/;
const ENUM_RE = /^[A-Z][A-Z0-9_]*$/;
export const MAX_STRING_CHARS = 48;

export class EncodingError extends Error {}

export function int(n: number): string {
  if (!Number.isSafeInteger(n) || n < 0) throw new EncodingError(`invalid integer: ${n}`);
  return String(n);
}

export function bytes(h: Hex, len?: number): string {
  if (typeof h !== 'string' || !HEX_RE.test(h)) throw new EncodingError(`invalid hex: ${h}`);
  if (len !== undefined && h.length !== len * 2) {
    throw new EncodingError(`expected ${len} bytes, got ${h.length / 2}`);
  }
  return h;
}

export function str(s: string): string {
  if (typeof s !== 'string') throw new EncodingError('string expected');
  const n = s.normalize('NFC');
  if (/[|,\n]/.test(n)) throw new EncodingError(`string contains a reserved character: ${s}`);
  // Length counts code points, not UTF-16 units.
  if ([...n].length > MAX_STRING_CHARS) throw new EncodingError(`string longer than 48 code points: ${s}`);
  return n;
}

export function bytesList(list: Hex[], len?: number): string {
  if (!Array.isArray(list)) throw new EncodingError('list of bytes expected');
  return list.map((h) => bytes(h, len)).sort().join(',');
}

const utf8Compare = (a: string, b: string): number => {
  const x = utf8ToBytes(a);
  const y = utf8ToBytes(b);
  for (let i = 0; i < Math.min(x.length, y.length); i++) if (x[i] !== y[i]) return x[i] - y[i];
  return x.length - y.length;
};

// List of strings: each rendered as a string, sorted by UTF-8 bytes (= code point order).
export function strList(list: string[]): string {
  if (!Array.isArray(list)) throw new EncodingError('list of strings expected');
  return list.map(str).sort(utf8Compare).join(',');
}

export function enumToken(t: string, allowed?: readonly string[]): string {
  if (typeof t !== 'string' || !ENUM_RE.test(t)) throw new EncodingError(`invalid enum token: ${t}`);
  if (allowed && !allowed.includes(t)) throw new EncodingError(`enum token not allowed: ${t}`);
  return t;
}

export function canonical(type: string, fields: string[]): string {
  enumToken(type);
  return ['SC1', type, ...fields].join('|');
}

export function sha256Hex(data: Uint8Array): Hex {
  return bytesToHex(sha256(data));
}

export function digestOf(canonicalString: string): Hex {
  return sha256Hex(utf8ToBytes(canonicalString));
}

// base64url without padding <-> hex

const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
const B64_INDEX: Record<string, number> = Object.fromEntries([...B64].map((c, i) => [c, i]));

export function hexToB64u(h: Hex): string {
  const b = hexToBytes(bytes(h));
  let out = '';
  for (let i = 0; i < b.length; i += 3) {
    const n = (b[i] << 16) | ((b[i + 1] ?? 0) << 8) | (b[i + 2] ?? 0);
    const chars = Math.min(4, Math.ceil(((b.length - i) * 8) / 6));
    for (let j = 0; j < chars; j++) out += B64[(n >> (18 - 6 * j)) & 63];
  }
  return out;
}

/** Strict base64url without padding; rejects non-canonical encodings (§7.3). */
export function b64uToHex(s: string): Hex {
  if (typeof s !== 'string' || !/^[A-Za-z0-9_-]*$/.test(s) || s.length % 4 === 1) {
    throw new EncodingError(`invalid base64url: ${s}`);
  }
  const out: number[] = [];
  for (let i = 0; i < s.length; i += 4) {
    const chunk = s.slice(i, i + 4);
    let n = 0;
    for (let j = 0; j < 4; j++) n = (n << 6) | (j < chunk.length ? B64_INDEX[chunk[j]] : 0);
    const nBytes = chunk.length - 1;
    for (let j = 0; j < nBytes; j++) out.push((n >> (16 - 8 * j)) & 255);
  }
  const hex = bytesToHex(Uint8Array.from(out));
  if (hexToB64u(hex) !== s) throw new EncodingError(`non-canonical base64url: ${s}`);
  return hex;
}

export { bytesToHex, hexToBytes };
