// Secure Enclave P-256 key (§19.6). Signs 32-byte digests; returns DER (convert with derToRaw).
import { requireOptionalNativeModule } from 'expo';

interface ScKeysNative {
  isAvailable(): boolean;
  getOrCreatePublicKey(tag: string): string; // uncompressed SEC1 hex (65 bytes)
  signDigest(tag: string, digestHex: string): string; // DER hex
  deleteKey(tag: string): void;
}

export const ScKeys = requireOptionalNativeModule<ScKeysNative>('ScKeys');
