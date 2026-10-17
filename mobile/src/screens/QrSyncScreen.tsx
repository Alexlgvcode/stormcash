// QR sync fallback (§10.7): the same session as Multipeer, taking turns showing and scanning
// QR frame sequences. Fully offline; both sides still write a CONTACT entry.
import { useEffect, useRef, useState } from 'react';
import { QrCode } from '../components/QrCode';
import { Scanner } from '../components/Scanner';
import { Body, Button, Muted, Screen, Title } from '../components/ui';
import { useNav } from '../nav';
import { syncManager } from '../sync/manager';
import { FrameCollector, toFrames } from '../sync/qrframes';
import type { SessionResult, SyncMessage, SyncSession } from '../sync/session';

const QR_TIMEOUT_MS = 5 * 60_000;
const FRAME_MS = 450;

type Mode = 'choose' | 'show' | 'scan' | 'done';

export function QrSyncScreen() {
  const nav = useNav();
  const [mode, setMode] = useState<Mode>('choose');
  const [frames, setFrames] = useState<string[]>([]);
  const [frameIdx, setFrameIdx] = useState(0);
  const [progress, setProgress] = useState('');
  const [result, setResult] = useState<string | null>(null);
  const session = useRef<SyncSession | null>(null);
  const outbox = useRef<SyncMessage[]>([]);
  const collector = useRef(new FrameCollector());
  const batch = useRef(0);

  useEffect(() => {
    if (mode !== 'show' || frames.length < 2) return;
    const id = setInterval(() => setFrameIdx((i) => (i + 1) % frames.length), FRAME_MS);
    return () => clearInterval(id);
  }, [mode, frames]);

  const newSession = () =>
    syncManager.newSession(
      (m) => outbox.current.push(m),
      (r: SessionResult | null, err?: string) =>
        setResult(r ? `Synced with ${r.peerLabel ?? r.peerPub.slice(0, 8)}: got ${r.received}, sent ${r.sent}` : `Failed: ${err}`),
      QR_TIMEOUT_MS,
    );

  const showOutbox = () => {
    const msgs = outbox.current.splice(0);
    if (msgs.length === 0) {
      setMode('done');
      return;
    }
    batch.current += 1;
    setFrames(toFrames(`${Date.now().toString(36)}-${batch.current}`, msgs));
    setFrameIdx(0);
    setMode('show');
  };

  const startFirst = () => {
    session.current = newSession();
    session.current.start();
    showOutbox();
  };

  const onFrame = (qr: string) => {
    const msgs = collector.current.add(qr);
    setProgress(`${collector.current.received} of ${collector.current.total} frames`);
    if (!msgs) return;
    collector.current = new FrameCollector();
    if (!session.current) {
      session.current = newSession();
      session.current.start();
    }
    for (const m of msgs) session.current.handle(m);
    showOutbox();
  };

  if (mode === 'choose') {
    return (
      <Screen>
        <Title>Sync by QR</Title>
        <Muted>Use this when phones can't link over Bluetooth or Wi-Fi. One phone starts; the other scans first.</Muted>
        <Button title="Start (show my code)" onPress={startFirst} />
        <Button title="Join (scan their code)" kind="secondary" onPress={() => setMode('scan')} />
        <Button title="Back" kind="secondary" onPress={() => nav.go({ name: 'records' })} />
      </Screen>
    );
  }
  if (mode === 'show') {
    return (
      <Screen>
        <Title>Let the other phone scan</Title>
        <QrCode value={frames[frameIdx] ?? ''} />
        <Muted>Frame {frameIdx + 1} of {frames.length}</Muted>
        {result ? <Body>{result}</Body> : null}
        <Button
          title={result ? 'Done' : 'Next: scan their code'}
          onPress={() => (result ? setMode('done') : setMode('scan'))}
        />
      </Screen>
    );
  }
  if (mode === 'scan') {
    return (
      <Screen>
        <Title>Scan the other phone</Title>
        <Scanner continuous onScan={onFrame} />
        <Muted>{progress || 'Waiting for frames…'}</Muted>
        <Button title="Cancel" kind="secondary" onPress={() => nav.go({ name: 'records' })} />
      </Screen>
    );
  }
  return (
    <Screen>
      <Title>QR sync</Title>
      <Body>{result ?? 'Finished.'}</Body>
      <Button title="Back to records" onPress={() => nav.go({ name: 'records' })} />
    </Screen>
  );
}
