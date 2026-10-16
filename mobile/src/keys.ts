// Software P-256 device key in SecureStore (§19.1). Secure Enclave swap is #36.
import * as SecureStore from 'expo-secure-store';
import { newPrivateKey, publicKeyOf, type Hex } from './protocol';

import { KEY_NAME } from './config';
export { KEY_REF } from './config';

export interface DeviceKey { priv: Hex; pub: Hex }

let cached: DeviceKey | null = null;

export async function getDeviceKey(): Promise<DeviceKey> {
  if (cached) return cached;
  let priv = await SecureStore.getItemAsync(KEY_NAME);
  if (!priv) {
    priv = newPrivateKey();
    await SecureStore.setItemAsync(KEY_NAME, priv, {
      keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
    });
  }
  cached = { priv, pub: publicKeyOf(priv) };
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
}

export const shortId = (pub: Hex): string => pub.slice(0, 8); // = deviceShortId (§10.2)
