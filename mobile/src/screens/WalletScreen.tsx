// Resident home (§19.2): remaining balance, cert status, Storm Mode, records carried.
import { useState } from 'react';
import { Alert } from 'react-native';
import * as api from '../api';
import { Header } from '../components/Header';
import { View } from 'react-native';
import { Big, Body, Button, Card, Field, Label, Meter, Muted, Pill, Row, Screen, wholeDollars } from '../components/ui';
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
    try {
      const next = await api.stormMode(cert.cert_id, STORM_CAP);
      const pub = getServerPub();
      if (pub && !verifyObject('CERT', next, pub)) throw new Error('Server signature is invalid');
      saveCertVersion(next, KEY_REF);
      nav.refresh();
    } catch (e) {
      Alert.alert('Storm Mode failed', e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const status = frozen
    ? { text: 'Certificate frozen', tone: 'red' as const }
    : expired
      ? { text: 'Certificate expired', tone: 'amber' as const }
      : { text: 'Backed by Capital One', tone: 'green' as const };

  return (
    <Screen>
      <Header />

      <Card tone="navy" style={{ gap: 14 }}>
        <Row style={{ justifyContent: 'space-between' }}>
          <Label color="#9DB4FF">{getDisplayName() ?? 'Wallet'} · works offline</Label>
          <Pill text={status.text} tone={status.tone} dot />
        </Row>
        <Big color="#fff">{wholeDollars(left)}</Big>
        <Muted color="#C7D2FE">left of {wholeDollars(cert.cap_cents)} · {wholeDollars(state.cumCents)} spent</Muted>
        <Meter value={state.cumCents} max={cert.cap_cents} color="#7C9CFF" track="#FFFFFF22" />
        <Muted color="#9DB4FF">{expired ? 'Renews when any phone reaches the internet' : `Renews in ${hoursLeft} h`}</Muted>
      </Card>

      <Button title="Pay a shop" subtitle="Scan the shop's code" big onPress={() => nav.go({ name: 'pay' })}
        disabled={frozen || expired || left === 0} />

      <Card>
        <Row style={{ justifyContent: 'space-between' }}>
          <View style={{ flex: 1, gap: 4 }}>
            <Body>Storm Mode</Body>
            <Muted>
              {cert.cap_cents >= STORM_CAP
                ? `On. Capital One holds ${wholeDollars(cert.cap_cents)} in escrow for you.`
                : `Raise your offline limit to ${wholeDollars(STORM_CAP)} before the storm.`}
            </Muted>
          </View>
          <Pill text={cert.cap_cents >= STORM_CAP ? 'On' : 'Off'} tone={cert.cap_cents >= STORM_CAP ? 'blue' : 'neutral'} />
        </Row>
        {cert.cap_cents < STORM_CAP ? (
          <Button
            title={online ? (busy ? 'Turning on…' : `Turn on Storm Mode`) : 'Storm Mode needs internet'}
            kind="secondary"
            onPress={stormMode}
            disabled={!online || busy}
          />
        ) : null}
      </Card>

      <Card>
        <Field label="Records carried" value={String(carrying)} />
        <Field label="Certificate" value={`v${cert.cert_ver} · ${cert.cert_id.slice(0, 8)}`} last />
        <Button title="Records & sync" kind="ghost" onPress={() => nav.go({ name: 'records' })} />
      </Card>
    </Screen>
  );
}
