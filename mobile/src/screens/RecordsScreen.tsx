// Records (§19.2): items carried by kind, nearby peers, last sync, last upload + hops, QR sync.
import { useEffect, useReducer } from 'react';
import { Big, Button, Card, Field, Label, Muted, Pill, Row, Screen, Section, Title, TopBar } from '../components/ui';
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

  const KIND_NAMES: Record<string, [string, string]> = {
    PAY: ['payment', 'payments'], TAG: ['spend tag', 'spend tags'], PROOF: ['proof', 'proofs'],
    DLOG: ['log entry', 'log entries'], POLICY: ['policy', 'policies'], RCPT: ['receipt', 'receipts'],
    CERT: ['certificate', 'certificates'], RENEW: ['renewal', 'renewals'],
  };
  const kindName = (k: string, n: number) => (KIND_NAMES[k] ? KIND_NAMES[k][n === 1 ? 0 : 1] : k);

  return (
    <Screen>
      <TopBar onBack={nav.home} />
      <Title>Records</Title>
      <Muted>This phone carries records shop to shop until any phone finds a signal and uploads them.</Muted>

      <Card>
        <Row style={{ justifyContent: 'space-between' }}>
          <Label>Carrying</Label>
          <Big>{String(total)}</Big>
        </Row>
        <Row>
          {Object.entries(counts).length
            ? Object.entries(counts).map(([k, n]) => (
              <Pill key={k} text={`${n} ${kindName(k, n ?? 0)}`} tone={k === 'PROOF' ? 'red' : k === 'PAY' ? 'blue' : 'neutral'} />
            ))
            : <Muted>Nothing to deliver</Muted>}
        </Row>
      </Card>

      <Section title="Nearby phones" right={<Pill text={connected.length ? `${connected.length} connected` : 'None'} tone={connected.length ? 'green' : 'neutral'} dot />}>
        <Card>
          {recentPeers(5).length === 0 ? <Muted>No phones met yet. Keep the app open near other phones.</Muted> : null}
          {recentPeers(5).map((p, i, all) => (
            <Field
              key={p.peer_pub}
              label={p.label ?? p.peer_pub.slice(0, 8)}
              value={`${p.sessions} syncs · ${ago(p.last_seen)}`}
              last={i === all.length - 1}
            />
          ))}
        </Card>
      </Section>

      <Section title="Sync">
        <Card>
          <Field
            label="Last sync"
            value={lastSync
              ? `${lastSync.peerLabel ?? lastSync.peerPub.slice(0, 8)} · +${lastSync.received} / ${lastSync.sent} sent · ${ago(lastSync.ts)}`
              : 'Not yet'}
          />
          {lastSync?.rejected ? <Field label="Rejected" value={`${lastSync.rejected} invalid items`} /> : null}
          <Field
            label="Last upload"
            value={up ? `${up.sent} records · ${Math.max(0, up.maxHops - 1)} hops · ${ago(up.ts)}` : 'Not yet'}
            last
          />
          {lastError ? <Pill text={lastError} tone="red" /> : null}
        </Card>
      </Section>

      <Button
        title={uploading ? 'Uploading…' : online ? 'Upload now' : 'Upload needs internet'}
        disabled={!online || uploading}
        onPress={() => syncManager.upload()}
      />
      <Button title="Sync by QR" kind="secondary" onPress={() => nav.go({ name: 'qrsync' })} />
    </Screen>
  );
}
