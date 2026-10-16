// Transport interface (§19.5). Implementations: Multipeer (nearby.ts) and QR (qr sync screen).
export interface Peer {
  id: string; // transport-level id
  name: string; // "<LABEL>:<shortId>" or "<shortId>"
}

export interface Transport {
  start(deviceName: string): Promise<void>;
  onPeer(cb: (peer: Peer, connected: boolean) => void): void;
  onMessage(cb: (peer: Peer, text: string) => void): void;
  send(peer: Peer, text: string): Promise<void>;
  stop(): Promise<void>;
}
