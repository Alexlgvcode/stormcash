// Resident home (§19.2): remaining balance, cert status, Storm Mode, records carried.
import { useEffect, useReducer, useState } from 'react';
import * as api from '../api';
import { Header } from '../components/Header';
import { StyleSheet, Text, View } from 'react-native';
import { Radar } from '../components/Radar';
import { syncManager } from '../sync/manager';
import { Button, Cell, colors, ErrorNote, font, Group, Meter, Screen, Status, wholeDollars } from '../components/ui';
import { useOnline } from '../hooks';
import { KEY_REF } from '../keys';
import { useNav } from '../nav';
import { verifyObject } from '../protocol';
import { getDisplayName, getServerPub } from '../settings';
import { countsByKind, nowS } from '../store/items';
import { currentPolicy } from '../store/policy';
import { latestCert, saveCertVersion, walletState } from '../store/wallet';

const STORM_CAP = 5000;

export function WalletScreen() {
  const nav = useNav();
  const online = useOnline();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [, rerender] = useReducer((x: number) => x + 1, 0);
  useEffect(() => syncManager.subscribe(rerender), []);
  const nearby = syncManager.status.connected.length;
  const cert = latestCert();
  const state = walletState();
  if (!cert || !state) return null;

  const left = Math.max(0, cert.cap_cents - state.cumCents);
  const frozen = currentPolicy()?.frozen_certs.includes(cert.cert_id) ?? false;
  const expired = cert.expires_at < nowS();
  const carrying = Object.values(countsByKind()).reduce((a, b) => a + (b ?? 0), 0);
  const hoursLeft = Math.max(0, Math.round((cert.expires_at - nowS()) / 3600));

  const stormMode = async () => {
    setBusy(true);
    setError(null);
    try {
      const next = await api.stormMode(cert.cert_id, STORM_CAP);
      const pub = getServerPub();
      if (pub && !verifyObject('CERT', next, pub)) throw new Error('Server signature is invalid');
      saveCertVersion(next, KEY_REF);
      nav.refresh();
    } catch (e) {
      setError(`Storm Mode failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const status = frozen
    ? { text: 'Certificate frozen', tone: 'red' as const }
    : expired
      ? { text: 'Certificate expired', tone: 'amber' as const }
      : { text: 'Backed by Capital One', tone: 'green' as const };
  const storm = cert.cap_cents >= STORM_CAP;

  return (
    <Screen>
      <Header />

      <View style={styles.hero}>
        <Radar blips={nearby} />
        <Text style={styles.heroLabel}>{getDisplayName() ?? 'Your wallet'} can spend</Text>
        <Text style={styles.heroFigure} adjustsFontSizeToFit numberOfLines={1}>{wholeDollars(left)}</Text>
        <Text style={styles.heroSub}>of {wholeDollars(cert.cap_cents)}, with no internet</Text>
        <View style={{ marginTop: 18, gap: 12 }}>
          <Meter value={state.cumCents} max={cert.cap_cents} color={colors.primary} track={colors.well} />
          <Status text={status.text} tone={status.tone} />
        </View>
      </View>

      <Button title="Pay a shop" subtitle="Scan the shop's code" big onPress={() => nav.go({ name: 'pay' })}
        disabled={frozen || expired || left === 0} />

      <Group>
        <Cell
          title="Storm Mode"
          detail={storm ? `On. Capital One holds ${wholeDollars(cert.cap_cents)} in escrow.` : `Raise your limit to ${wholeDollars(STORM_CAP)} before the storm.`}
          accessory={storm ? <Text style={styles.on}>On</Text> : undefined}
        />
        <Cell title="Records carried" detail="Delivered phone to phone" value={String(carrying)} onPress={() => nav.go({ name: 'records' })} />
        <Cell title="Certificate" detail={expired ? 'Renews when any phone is online' : `Renews in ${hoursLeft} h`} value={`v${cert.cert_ver}`} />
      </Group>
      {!storm ? (
        <Button
          title={online ? 'Turn on Storm Mode' : 'Storm Mode needs internet'}
          kind="secondary"
          onPress={stormMode}
          busy={busy}
          disabled={!online}
        />
      ) : null}
      {error ? <ErrorNote text={error} /> : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  hero: { paddingTop: 28, paddingBottom: 8, minHeight: 250 },
  heroLabel: { fontFamily: font.medium, fontSize: 17, color: colors.muted },
  heroFigure: { fontFamily: font.heavy, fontSize: 96, lineHeight: 104, color: colors.ink, letterSpacing: -4, fontVariant: ['tabular-nums'] },
  heroSub: { fontFamily: font.medium, fontSize: 17, color: colors.muted },
  on: { fontFamily: font.semibold, fontSize: 17, color: colors.primary },
});
