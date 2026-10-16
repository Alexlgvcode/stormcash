// Resident home (§19.2): remaining balance, cert status, Storm Mode, records carried.
import { useState } from 'react';
import { Alert } from 'react-native';
import * as api from '../api';
import { Header } from '../components/Header';
import { Big, Body, Button, colors, Muted, Screen, wholeDollars } from '../components/ui';
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

  return (
    <Screen>
      <Header />
      <Muted>{getDisplayName()}</Muted>
      <Big>{wholeDollars(left)} of {wholeDollars(cert.cap_cents)} left</Big>
      <Body color={frozen || expired ? colors.red : colors.green}>
        {frozen ? 'Certificate frozen' : expired ? 'Certificate expired' : `Backed by Capital One · renews in ${hoursLeft} h`}
      </Body>
      <Muted>Carrying {carrying} records</Muted>

      <Button title="Pay" onPress={() => nav.go({ name: 'pay' })} disabled={frozen || left === 0} />
      {cert.cap_cents < STORM_CAP ? (
        <Button
          title={online ? (busy ? 'Turning on…' : `Storm Mode: raise to ${wholeDollars(STORM_CAP)}`) : 'Storm Mode needs internet'}
          kind="secondary"
          onPress={stormMode}
          disabled={!online || busy}
        />
      ) : (
        <Muted>Storm Mode on</Muted>
      )}
      <Button title="Records" kind="secondary" onPress={() => nav.go({ name: 'records' })} />
    </Screen>
  );
}
