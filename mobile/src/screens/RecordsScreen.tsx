// Records (§19.2): items carried by kind, nearby peers, last sync, last upload + hops, QR sync.
import { useEffect, useReducer } from 'react';
import { Button, Body, Muted, Screen, Title } from '../components/ui';
import { useOnline } from '../hooks';
import { useNav } from '../nav';
import { countsByKind } from '../store/items';
import { recentPeers } from '../store/peers';
import { syncManager } from '../sync/manager';
import { lastUpload } from '../sync/upload';

const ago = (ts: number) => {
  const s = Math.max(0, Math.floor(Date.now() / 1000) - ts);
  return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.floor(s / 60)} min ago` : `${Math.floor(s / 3600)} h ago`;
};

export function RecordsScreen() {
  const nav = useNav();
  const online = useOnline();
  const [, rerender] = useReducer((x: number) => x + 1, 0);
  useEffect(() => syncManager.subscribe(rerender), []);

  const counts = countsByKind();
  const total = Object.values(counts).reduce((a, b) => a + (b ?? 0), 0);
  const { connected, lastSync, lastError, uploading } = syncManager.status;
  const up = lastUpload();

  return (
    <Screen>
      <Title>Records</Title>
      <Body>Carrying {total} records</Body>
      <Muted>
        {Object.entries(counts).map(([k, n]) => `${k} ${n}`).join(' · ') || 'Nothing to deliver'}
      </Muted>

      <Body>Nearby phones</Body>
      <Muted>{connected.length ? connected.map((p) => p.name).join(', ') : 'None connected'}</Muted>
      {recentPeers(5).map((p) => (
        <Muted key={p.peer_pub}>
          {p.label ?? p.peer_pub.slice(0, 8)} · {p.sessions} syncs · last {ago(p.last_seen)}
        </Muted>
      ))}

      <Body>Last sync</Body>
      <Muted>
        {lastSync
          ? `${lastSync.peerLabel ?? lastSync.peerPub.slice(0, 8)} · got ${lastSync.received}, sent ${lastSync.sent}` +
            `${lastSync.rejected ? `, rejected ${lastSync.rejected}` : ''} · ${ago(lastSync.ts)}`
          : 'Not yet'}
      </Muted>
      {lastError ? <Muted>{lastError}</Muted> : null}

      <Body>Last upload</Body>
      <Muted>
        {up ? `${up.sent} records · ${up.receipted} receipted · up to ${Math.max(0, up.maxHops - 1)} hops · ${ago(up.ts)}` : 'Not yet'}
      </Muted>

      <Button
        title={uploading ? 'Uploading…' : online ? 'Upload now' : 'Upload needs internet'}
        kind="secondary"
        disabled={!online || uploading}
        onPress={() => syncManager.upload()}
      />
      <Button title="Sync by QR" kind="secondary" onPress={() => nav.go({ name: 'qrsync' })} />
      <Button title="Back" kind="secondary" onPress={nav.home} />
    </Screen>
  );
}
