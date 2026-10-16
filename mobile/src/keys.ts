// Device key (§19.1): a software P-256 key in SecureStore, or, when switched on in the demo menu
// before setup, a Secure Enclave key (§19.6). The enclave key is the fallback-switched option.
import * as SecureStore from 'expo-secure-store';
import { ScKeys } from '../modules/sc-keys';
import { KEY_NAME } from './config';
import {
  compressPublicKey, derToRaw, EXTERNAL_KEY_PREFIX, newPrivateKey, publicKeyOf, setExternalSigner, type Hex,
} from './protocol';
import { getSetting, setSetting } from './store/db';
export { KEY_REF } from './config';

const ENCLAVE_TAG = 'edu.bu.stormcash.device';

export interface DeviceKey { priv: Hex; pub: Hex; hardware: boolean }

let cached: DeviceKey | null = null;

export const enclaveAvailable = (): boolean => !!ScKeys?.isAvailable();
export const wantsEnclave = (): boolean => getSetting('key_kind') === 'enclave';
export const setWantsEnclave = (on: boolean): void => setSetting('key_kind', on ? 'enclave' : 'software');

setExternalSigner((_ref, digest) => derToRaw(ScKeys!.signDigest(ENCLAVE_TAG, digest)));

export async function getDeviceKey(): Promise<DeviceKey> {
  if (cached) return cached;
  if (wantsEnclave() && enclaveAvailable()) {
    try {
      const pub = compressPublicKey(ScKeys!.getOrCreatePublicKey(ENCLAVE_TAG));
      cached = { priv: EXTERNAL_KEY_PREFIX + ENCLAVE_TAG, pub, hardware: true };
      return cached;
    } catch {
      setWantsEnclave(false); // fall back to the software key
    }
  }
  let priv = await SecureStore.getItemAsync(KEY_NAME);
  if (!priv) {
    priv = newPrivateKey();
    await SecureStore.setItemAsync(KEY_NAME, priv, {
      keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
    });
  }
  cached = { priv, pub: publicKeyOf(priv), hardware: false };
  return cached;
}

/** Synchronous access after getDeviceKey() resolved once at startup. */
export function deviceKey(): DeviceKey {
  if (!cached) throw new Error('device key not loaded');
  return cached;
}

export async function deleteDeviceKey(): Promise<void> {
  cached = null;
  await SecureStore.deleteItemAsync(KEY_NAME);
  try {
    ScKeys?.deleteKey(ENCLAVE_TAG);
  } catch {
    // no enclave key
  }
}

export const shortId = (pub: Hex): string => pub.slice(0, 8); // = deviceShortId (§10.2)
