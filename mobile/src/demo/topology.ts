// Demo topology (§10.6): Pharmacy ↔ Maya ↔ Gas Station. Pharmacy and Gas Station never link,
// so the pharmacy's records reach the gas station only through Maya's phone.
import type { DemoLabel } from '../settings';
import { getSetting } from '../store/db';

export const ALLOWLIST: Record<DemoLabel, DemoLabel[]> = {
  MAYA: ['PHARMACY', 'GAS_STATION'],
  PHARMACY: ['MAYA'],
  GAS_STATION: ['MAYA'],
};

export const isTopologyOn = (): boolean => getSetting('demo_topology') === '1';

/** Peer names on the transport are "<LABEL>:<shortId>" or just "<shortId>". */
export const labelOfPeerName = (name: string): DemoLabel | null => {
  const l = name.split(':')[0];
  return l in ALLOWLIST ? (l as DemoLabel) : null;
};

export function allowedPeer(myLabel: DemoLabel | null, peerName: string): boolean {
  if (!isTopologyOn()) return true;
  const peer = labelOfPeerName(peerName);
  return !!myLabel && !!peer && ALLOWLIST[myLabel].includes(peer);
}
