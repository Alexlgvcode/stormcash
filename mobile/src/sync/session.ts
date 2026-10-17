// Sync session (§10.3): HELLO ↔ HELLO, WANT, ITEMS (chunked), DONE, then a CONTACT log entry.
// Symmetric and transport-agnostic: Multipeer and QR sync both drive it through a Channel.
import {
  b64uToHex, contactId, deviceShortId, hexToB64u, id8, itemBodyFromWire, itemBodyToWire, randomHex,
  type Hex, type ItemKind,
} from '../protocol';
import { appendLog } from '../store/devicelog';
import { inventory, inventoryOfKind, itemsById8, type PathHop } from '../store/items';
import { currentPolicy } from '../store/policy';
import { recordSession } from '../store/peers';
import { storeVerified } from './apply';
import { verifyItem } from './verify';

export interface Channel {
  send(msg: SyncMessage): void;
}

type WireItem = { kind: ItemKind; body: Record<string, unknown>; path: PathHop[] };

export type SyncMessage =
  // `pays` (§10.3, v4.3): the inv ids held as a full PAY, so a peer holding only the bare TAG
  // with the same id still asks for the PAY the server needs to settle it. `lb` is the demo label.
  | { t: 'HELLO'; v: 1; dp: string; role: string; n: string; pv: number; inv: string[]; pays: string[]; lb?: string }
  | { t: 'WANT'; ids: string[] }
  | { t: 'ITEMS'; items: WireItem[] }
  | { t: 'DONE' };

export interface SessionIdentity {
  priv: Hex;
  pub: Hex;
  role: string;
  label: string | null;
}

export interface SessionResult {
  peerPub: Hex;
  peerLabel: string | null;
  contactId: Hex;
  received: number;
  sent: number;
  rejected: number;
}

const MAX_MESSAGE_BYTES = 64 * 1024;
const MAX_LOGGED_IDS = 200;
export const SESSION_TIMEOUT_MS = 15_000;
// Item kinds whose ids go into CONTACT entries. PAY shares its id with its TAG, so it counts too;
// otherwise a tag delivered inside a PAY would never show up as evidence for R5 (§9.4 b).
const LOGGED_KINDS = new Set<ItemKind>(['TAG', 'PAY', 'PROOF']);

export class SyncSession {
  private nonce = randomHex(16);
  private peerHello: Extract<SyncMessage, { t: 'HELLO' }> | null = null;
  private sentDone = false;
  private recvDone = false;
  private trusted = true;
  private sentIds: Hex[] = [];
  private recvIds: Hex[] = [];
  private received = 0;
  private rejected = 0;
  private finished = false;
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private channel: Channel,
    private me: SessionIdentity,
    private serverPub: Hex,
    private now: () => number,
    private onFinish: (r: SessionResult | null, error?: string) => void,
  ) {}

  start(): void {
    this.timer = setTimeout(() => this.fail('timeout'), SESSION_TIMEOUT_MS);
    this.channel.send({
      t: 'HELLO', v: 1, dp: hexToB64u(this.me.pub), role: this.me.role, n: hexToB64u(this.nonce),
      pv: currentPolicy()?.policy_ver ?? 0, inv: inventory().map(hexToB64u),
      pays: inventoryOfKind('PAY').map(hexToB64u),
      ...(this.me.label ? { lb: this.me.label } : {}),
    });
  }

  handle(msg: SyncMessage): void {
    if (this.finished) return;
    try {
      switch (msg.t) {
        case 'HELLO': return this.onHello(msg);
        case 'WANT': return this.onWant(msg);
        case 'ITEMS': return this.onItems(msg);
        case 'DONE':
          this.recvDone = true;
          return this.maybeFinish();
      }
    } catch (e) {
      this.fail(e instanceof Error ? e.message : String(e));
    }
  }

  private onHello(h: Extract<SyncMessage, { t: 'HELLO' }>): void {
    if (h.v !== 1) throw new Error(`unsupported sync version ${h.v}`);
    this.peerHello = h;
    const mine = new Set(inventory());
    // Includes the peer's newer POLICY, if any, since it is in their inventory (§10.3).
    const want = h.inv.map(b64uToHex).filter((x) => !mine.has(x));
    const tagOnly = new Set(inventoryOfKind('TAG'));
    for (const x of (h.pays ?? []).map(b64uToHex)) if (tagOnly.has(x)) want.push(x);
    this.channel.send({ t: 'WANT', ids: want.map(hexToB64u) });
  }

  private onWant(w: Extract<SyncMessage, { t: 'WANT' }>): void {
    const items = itemsById8(w.ids.map(b64uToHex)); // highest priority first
    let batch: WireItem[] = [];
    let size = 0;
    for (const it of items) {
      const wire: WireItem = { kind: it.kind, body: itemBodyToWire(it.kind, it.body), path: it.path };
      const len = JSON.stringify(wire).length;
      if (batch.length && size + len > MAX_MESSAGE_BYTES) {
        this.channel.send({ t: 'ITEMS', items: batch });
        batch = [];
        size = 0;
      }
      batch.push(wire);
      size += len;
      if (LOGGED_KINDS.has(it.kind)) this.sentIds.push(id8(it.itemId));
    }
    if (batch.length) this.channel.send({ t: 'ITEMS', items: batch });
    this.channel.send({ t: 'DONE' });
    this.sentDone = true;
    this.maybeFinish();
  }

  private onItems(m: Extract<SyncMessage, { t: 'ITEMS' }>): void {
    const now = this.now();
    const hop: PathHop = [deviceShortId(this.me.pub), now];
    for (const w of m.items) {
      if (!this.trusted) {
        this.rejected++;
        continue;
      }
      let ok = false;
      try {
        const body = itemBodyFromWire(w.kind, w.body);
        if (verifyItem(w.kind, body, this.serverPub)) {
          const { id, isNew } = storeVerified(w.kind, body, [...(w.path ?? []), hop], now);
          ok = true;
          if (isNew) this.received++;
          if (LOGGED_KINDS.has(w.kind)) this.recvIds.push(id8(id));
        }
      } catch {
        ok = false;
      }
      if (!ok) {
        // Invalid item: drop it and stop trusting this peer for the rest of the session.
        this.rejected++;
        this.trusted = false;
      }
    }
  }

  private maybeFinish(): void {
    if (!this.sentDone || !this.recvDone || !this.peerHello || this.finished) return;
    this.finished = true;
    if (this.timer) clearTimeout(this.timer);
    const peerPub = b64uToHex(this.peerHello.dp);
    const cid = contactId(this.me.pub, this.nonce, peerPub, b64uToHex(this.peerHello.n));
    const cap = (ids: Hex[]) => {
      const uniq = [...new Set(ids)];
      return { list: uniq.slice(0, MAX_LOGGED_IDS), overflow: Math.max(0, uniq.length - MAX_LOGGED_IDS) };
    };
    const sent = cap(this.sentIds);
    const recv = cap(this.recvIds);
    const now = this.now();
    appendLog({
      kind: 'CONTACT', contact_id: cid, peer_pub: peerPub, sent_ids: sent.list, recv_ids: recv.list,
      sent_overflow: sent.overflow, recv_overflow: recv.overflow,
    }, this.me.pub, this.me.priv, now);
    recordSession(peerPub, this.peerHello.lb ?? null, cid, now);
    this.onFinish({
      peerPub, peerLabel: this.peerHello.lb ?? null, contactId: cid,
      received: this.received, sent: new Set(this.sentIds).size, rejected: this.rejected,
    });
  }

  private fail(reason: string): void {
    if (this.finished) return;
    this.finished = true;
    if (this.timer) clearTimeout(this.timer);
    this.onFinish(null, reason);
  }
}
