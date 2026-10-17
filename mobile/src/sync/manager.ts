// Runs sync sessions over a transport, re-syncs connected peers, and uploads when online.
import * as Network from 'expo-network';
import { deviceKey, shortId } from '../keys';
import { getDemoLabel, getRole, getServerPub } from '../settings';
import { getSetting, setSetting } from '../store/db';
import { nowS } from '../store/items';
import type { Peer, Transport } from '../transport';
import { NearbyTransport } from '../transport/nearby';
import { SyncSession, type SessionResult, type SyncMessage } from './session';
import { uploadAll } from './upload';

const RESYNC_MS = 20_000;

export interface SyncStatus {
  connected: Peer[];
  lastSync: (SessionResult & { ts: number }) | null;
  lastError: string | null;
  uploading: boolean;
}

type Envelope = { sid: string; m: SyncMessage };

class SyncManager {
  private transport: Transport | null = null;
  private sessions = new Map<string, SyncSession>();
  private connected = new Map<string, Peer>();
  private timer: ReturnType<typeof setInterval> | null = null;
  private netSub: { remove(): void } | null = null;
  private listeners = new Set<() => void>();
  status: SyncStatus = { connected: [], lastSync: null, lastError: null, uploading: false };

  subscribe(cb: () => void): () => void {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  }

  private emit(patch: Partial<SyncStatus>) {
    this.status = { ...this.status, ...patch, connected: [...this.connected.values()] };
    this.listeners.forEach((l) => l());
  }

  myName(): string {
    const label = getDemoLabel();
    const sid = shortId(deviceKey().pub);
    return label ? `${label}:${sid}` : sid;
  }

  async start(): Promise<void> {
    if (this.transport) return;
    const t = new NearbyTransport();
    this.transport = t;
    t.onPeer((peer, isConnected) => {
      if (isConnected) {
        this.connected.set(peer.id, peer);
        if (this.myName() < peer.name) this.openSession(peer);
      } else {
        this.connected.delete(peer.id);
      }
      this.emit({});
    });
    t.onMessage((peer, text) => this.onText(peer, text));
    try {
      await t.start(this.myName());
    } catch (e) {
      this.emit({ lastError: `Multipeer failed to start: ${e instanceof Error ? e.message : String(e)}` });
    }
    this.timer = setInterval(() => {
      for (const p of this.connected.values()) if (this.myName() < p.name) this.openSession(p);
    }, RESYNC_MS);
    this.netSub = Network.addNetworkStateListener((s) => {
      if (s.isInternetReachable) this.upload().catch(() => {});
    });
  }

  async stop(): Promise<void> {
    if (this.timer) clearInterval(this.timer);
    this.netSub?.remove();
    await this.transport?.stop();
    this.transport = null;
    this.connected.clear();
    this.sessions.clear();
    this.emit({});
  }

  /** Runs a session against an arbitrary channel (used by QR sync). */
  newSession(send: (m: SyncMessage) => void, onDone: (r: SessionResult | null, err?: string) => void): SyncSession {
    const { priv, pub } = deviceKey();
    return new SyncSession({ send }, { priv, pub, role: getRole() ?? 'resident', label: getDemoLabel() },
      getServerPub(), nowS, (r, err) => {
        this.finished(r, err);
        onDone(r, err);
      });
  }

  private finished(r: SessionResult | null, err?: string) {
    if (r) this.emit({ lastSync: { ...r, ts: nowS() }, lastError: null });
    else this.emit({ lastError: `Sync failed: ${err}` });
  }

  private openSession(peer: Peer, sid = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`) {
    const session = this.newSession(
      (m) => this.transport?.send(peer, JSON.stringify({ sid, m } satisfies Envelope)).catch(() => {}),
      () => this.sessions.delete(sid),
    );
    this.sessions.set(sid, session);
    session.start();
    return session;
  }

  private onText(peer: Peer, text: string) {
    let env: Envelope;
    try {
      env = JSON.parse(text) as Envelope;
    } catch {
      return;
    }
    let s = this.sessions.get(env.sid);
    if (!s && env.m.t === 'HELLO') s = this.openSession(peer, env.sid); // responder side
    s?.handle(env.m);
  }

  async upload(): Promise<void> {
    if (this.status.uploading) return;
    this.emit({ uploading: true });
    try {
      await uploadAll(getServerPub(), nowS());
      this.emit({ uploading: false, lastError: null });
    } catch (e) {
      this.emit({ uploading: false, lastError: `Upload failed: ${e instanceof Error ? e.message : String(e)}` });
    }
  }
}

export const syncManager = new SyncManager();

export const isMultipeerEnabled = (): boolean => getSetting('multipeer') !== '0';
export const setMultipeerEnabled = (on: boolean): void => setSetting('multipeer', on ? '1' : '0');
