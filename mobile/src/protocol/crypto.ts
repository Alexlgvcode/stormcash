// ECDSA P-256 over prehashed SHA-256 digests, raw r||s signatures, low-S on sign (§7.1).
import { p256 } from '@noble/curves/nist.js';
import { randomBytes as nobleRandomBytes } from '@noble/hashes/utils.js';
import { bytesToHex, hexToBytes, type Hex } from './encoding';

const N = p256.Point.CURVE().n;

export function randomHex(len = 16): Hex {
  return bytesToHex(nobleRandomBytes(len));
}

export function newPrivateKey(): Hex {
  return bytesToHex(p256.utils.randomSecretKey());
}

export function publicKeyOf(priv: Hex): Hex {
  return bytesToHex(p256.getPublicKey(hexToBytes(priv), true));
}

/** Signs a 32-byte digest (already SHA-256 of the canonical string). Returns raw low-S r||s. */
export function signDigest(digest: Hex, priv: Hex): Hex {
  const sig = p256.sign(hexToBytes(digest), hexToBytes(priv), { prehash: false, lowS: true });
  return bytesToHex(sig);
}

/** Accepts both low-S and high-S signatures. Never throws. */
export function verifyDigest(sig: Hex, digest: Hex, pub: Hex): boolean {
  try {
    if (sig.length !== 128 || digest.length !== 64) return false;
    if (pub.length !== 66 || !(pub.startsWith('02') || pub.startsWith('03'))) return false;
    return p256.verify(hexToBytes(sig), hexToBytes(digest), hexToBytes(pub), {
      prehash: false,
      lowS: false,
    });
  } catch {
    return false;
  }
}

export function normalizeLowS(sig: Hex): Hex {
  const r = BigInt('0x' + sig.slice(0, 64));
  let s = BigInt('0x' + sig.slice(64));
  if (s > N / 2n) s = N - s;
  return r.toString(16).padStart(64, '0') + s.toString(16).padStart(64, '0');
}

/** DER (from Secure Enclave or Python `cryptography`) → raw r||s. Does not normalize S. */
export function derToRaw(der: Hex): Hex {
  const b = hexToBytes(der);
  let i = 0;
  const readLen = (): number => {
    let len = b[i++];
    if (len & 0x80) {
      const n = len & 0x7f;
      len = 0;
      for (let k = 0; k < n; k++) len = (len << 8) | b[i++];
    }
    return len;
  };
  const readInt = (): bigint => {
    if (b[i++] !== 0x02) throw new Error('DER: expected INTEGER');
    const len = readLen();
    const v = BigInt('0x' + (bytesToHex(b.subarray(i, i + len)) || '00'));
    i += len;
    return v;
  };
  if (b[i++] !== 0x30) throw new Error('DER: expected SEQUENCE');
  readLen();
  const r = readInt();
  const s = readInt();
  if (!(r > 0n && r < N && s > 0n && s < N)) throw new Error('DER: scalar out of range');
  return r.toString(16).padStart(64, '0') + s.toString(16).padStart(64, '0');
}

/** raw r||s → DER (minimal positive INTEGERs). */
export function rawToDer(sig: Hex): Hex {
  const int = (h: string) => {
    let v = h.replace(/^(00)+/, '') || '00';
    if (parseInt(v.slice(0, 2), 16) & 0x80) v = '00' + v;
    return '02' + (v.length / 2).toString(16).padStart(2, '0') + v;
  };
  const body = int(sig.slice(0, 64)) + int(sig.slice(64));
  return '30' + (body.length / 2).toString(16).padStart(2, '0') + body;
}

export const isLowS = (sig: Hex): boolean => BigInt('0x' + sig.slice(64)) <= N / 2n;
