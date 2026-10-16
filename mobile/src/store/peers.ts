// Peers seen over the sync transport (§19.4).
import type { Hex } from '../protocol';
import { getDb } from './db';

export interface PeerRow {
  peer_pub: Hex; label: string | null; last_seen: number; sessions: number; last_contact_id: Hex | null;
}

export function recordSession(peerPub: Hex, label: string | null, contactId: Hex, ts: number): void {
  getDb().runSync(
    `INSERT INTO peers (peer_pub, label, last_seen, sessions, last_contact_id) VALUES (?, ?, ?, 1, ?)
     ON CONFLICT(peer_pub) DO UPDATE SET label = COALESCE(excluded.label, label),
       last_seen = excluded.last_seen, sessions = sessions + 1, last_contact_id = excluded.last_contact_id`,
    peerPub, label, ts, contactId,
  );
}

export function recentPeers(limit = 10): PeerRow[] {
  return getDb().getAllSync<PeerRow>('SELECT * FROM peers ORDER BY last_seen DESC LIMIT ?', limit);
}
