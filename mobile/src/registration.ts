// Setup needs internet: key, register, receive cert / merchant cert, download policy (§19.1).
import * as api from './api';
import { DEMO_REGION } from './config';
import { getDeviceKey, KEY_REF } from './keys';
import { verifyObject } from './protocol';
import { setDisplayName, setResidentId, setRole, getServerPub, type DemoLabel, type Role } from './settings';
import { saveMerchantCert } from './store/merchant';
import { savePolicyIfNewer } from './store/policy';
import { saveCertVersion } from './store/wallet';

// Real demo phones sit at fixed spots on the town grid (§16.3). Keep in sync with sim/.
const MERCHANT_POSITIONS: Partial<Record<DemoLabel, [number, number]>> = {
  PHARMACY: [10, 8],
  GAS_STATION: [16, 8],
};

export async function register(role: Role, displayName: string, label: DemoLabel | null): Promise<string[]> {
  const warnings: string[] = [];
  await getDeviceKey();
  const serverPub = getServerPub();
  if (!serverPub) warnings.push('No server key set: certificates were not verified. Set it in the demo menu.');

  if (role === 'resident') {
    const { residentId, cert } = await api.registerResident(displayName, DEMO_REGION);
    if (serverPub && !verifyObject('CERT', cert, serverPub)) throw new Error('Server certificate signature is invalid');
    saveCertVersion(cert, KEY_REF);
    setResidentId(residentId);
  } else {
    const [x, y] = (label && MERCHANT_POSITIONS[label]) ?? [12, 10];
    const { mcert } = await api.registerMerchant(displayName, DEMO_REGION, x, y);
    if (serverPub && !verifyObject('MCERT', mcert, serverPub)) throw new Error('Merchant certificate signature is invalid');
    saveMerchantCert(mcert);
  }

  try {
    const policy = await api.fetchPolicy();
    if (policy && (!serverPub || verifyObject('POLICY', policy, serverPub))) savePolicyIfNewer(policy);
  } catch {
    warnings.push('Could not download the policy list yet.');
  }
  setDisplayName(displayName);
  setRole(role);
  return warnings;
}
