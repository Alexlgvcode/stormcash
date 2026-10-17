// Multipeer over expo-nearby-connections (§6.1). Advertise + browse while foregrounded; only
// peers on the demo-topology allowlist are invited or accepted (§10.6).
import * as Nearby from 'expo-nearby-connections';
import { allowedPeer } from '../demo/topology';
import { getDemoLabel } from '../settings';
import type { Peer, Transport } from './index';

const P2P_CLUSTER = 1;

export class NearbyTransport implements Transport {
  private myName = '';
  private names = new Map<string, string>(); // peerId → name
  private unsubs: (() => void)[] = [];
  private peerCb: (p: Peer, connected: boolean) => void = () => {};
  private msgCb: (p: Peer, text: string) => void = () => {};

  onPeer(cb: (p: Peer, connected: boolean) => void): void { this.peerCb = cb; }
  onMessage(cb: (p: Peer, text: string) => void): void { this.msgCb = cb; }

  async start(deviceName: string): Promise<void> {
    this.myName = deviceName;
    const allowed = (name: string) => allowedPeer(getDemoLabel(), name);
    this.unsubs.push(
      Nearby.onPeerFound(({ peerId, name }) => {
        this.names.set(peerId, name);
        // Only one side invites, so two phones don't open two sessions.
        if (allowed(name) && this.myName < name) Nearby.requestConnection(peerId).catch(() => {});
      }),
      Nearby.onInvitationReceived(({ peerId, name }) => {
        this.names.set(peerId, name);
        (allowed(name) ? Nearby.acceptConnection(peerId) : Nearby.rejectConnection(peerId)).catch(() => {});
      }),
      Nearby.onConnected(({ peerId, name }) => {
        this.names.set(peerId, name);
        this.peerCb({ id: peerId, name }, true);
      }),
      Nearby.onDisconnected(({ peerId }) => {
        this.peerCb({ id: peerId, name: this.names.get(peerId) ?? peerId }, false);
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
    await Nearby.stopAdvertise().catch(() => {});
    await Nearby.stopDiscovery().catch(() => {});
    await Nearby.disconnect().catch(() => {});
  }
}
