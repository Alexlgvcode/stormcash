// Face ID before every payment (§8.1 step 4). Falls back to the device passcode.
import * as LocalAuthentication from 'expo-local-authentication';

export async function confirmWithFaceId(promptMessage: string): Promise<boolean> {
  const hasHardware = await LocalAuthentication.hasHardwareAsync();
  const enrolled = hasHardware && (await LocalAuthentication.isEnrolledAsync());
  if (!enrolled) return true; // simulator / no biometrics: nothing to check
  const r = await LocalAuthentication.authenticateAsync({ promptMessage, disableDeviceFallback: false });
  return r.success;
}
