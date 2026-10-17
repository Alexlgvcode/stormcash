// Multipeer over expo-nearby-connections (§6.1). Advertise + browse while foregrounded; only
// peers on the demo-topology allowlist are invited or accepted (§10.6).
import * as Nearby from 'expo-nearby-connections';
import { allowedPeer } from '../demo/topology';
import { getDemoLabel } from '../settings';
import type { Peer, Transport } from './index';

const P2P_CLUSTER = 1;
const RETRY_MS = 2_000; // after a failed or dropped link, re-invite a peer that is still in range

export class NearbyTransport implements Transport {
  private myName = '';
  private names = new Map<string, string>(); // peerId → name
  private found = new Map<string, string>(); // name → latest discovered peerId (cleared when lost)
  // Peer names with an invitation in flight or a live connection. iOS can report the same phone
  // more than once (Bluetooth and Wi-Fi); a second invite while the first is connecting makes
  // MultipeerConnectivity drop both, so we invite each name once until it disconnects.
  private linking = new Set<string>();
  private retries = new Set<ReturnType<typeof setTimeout>>();
  private unsubs: (() => void)[] = [];
  private peerCb: (p: Peer, connected: boolean) => void = () => {};
  private msgCb: (p: Peer, text: string) => void = () => {};

  onPeer(cb: (p: Peer, connected: boolean) => void): void { this.peerCb = cb; }
  onMessage(cb: (p: Peer, text: string) => void): void { this.msgCb = cb; }

  private allowed(name: string): boolean {
    return allowedPeer(getDemoLabel(), name);
  }

  // Only one side invites (the smaller name), so two phones don't open two sessions.
  private invite(name: string): void {
    const peerId = this.found.get(name);
    if (!peerId || !this.allowed(name) || this.myName >= name || this.linking.has(name)) return;
    this.linking.add(name);
    Nearby.requestConnection(peerId).catch(() => this.linking.delete(name));
  }

  async start(deviceName: string): Promise<void> {
    this.myName = deviceName;
    this.unsubs.push(
      Nearby.onPeerFound(({ peerId, name }) => {
        this.names.set(peerId, name);
        this.found.set(name, peerId);
        this.invite(name);
      }),
      Nearby.onPeerLost(({ peerId }) => {
        const name = this.names.get(peerId);
        if (name && this.found.get(name) === peerId) this.found.delete(name);
      }),
      Nearby.onInvitationReceived(({ peerId, name }) => {
        this.names.set(peerId, name);
        (this.allowed(name) ? Nearby.acceptConnection(peerId) : Nearby.rejectConnection(peerId)).catch(() => {});
      }),
      Nearby.onConnected(({ peerId, name }) => {
        this.names.set(peerId, name);
        this.peerCb({ id: peerId, name }, true);
      }),
      Nearby.onDisconnected(({ peerId }) => {
        const name = this.names.get(peerId) ?? peerId;
        // Also fires when an invitation fails. The browser won't report a peer that is still in
        // range again, so retry it ourselves.
        this.linking.delete(name);
        const t = setTimeout(() => {
          this.retries.delete(t);
          this.invite(name);
        }, RETRY_MS);
        this.retries.add(t);
        this.peerCb({ id: peerId, name }, false);
      }),
      Nearby.onTextReceived(({ peerId, text }) => {
        this.msgCb({ id: peerId, name: this.names.get(peerId) ?? peerId }, text);
      }),
    );
    await Nearby.startAdvertise(deviceName, P2P_CLUSTER as never);
    await Nearby.startDiscovery(deviceName, P2P_CLUSTER as never);
  }

  async send(peer: Peer, text: string): Promise<void> {
    await Nearby.sendText(peer.id, text);
  }

  async stop(): Promise<void> {
    this.unsubs.forEach((u) => u());
    this.unsubs = [];
    this.retries.forEach(clearTimeout);
    this.retries.clear();
    this.linking.clear();
    this.found.clear();
    await Nearby.stopAdvertise().catch(() => {});
    await Nearby.stopDiscovery().catch(() => {});
    await Nearby.disconnect().catch(() => {});
  }
}
