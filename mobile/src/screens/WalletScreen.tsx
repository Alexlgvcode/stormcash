// Resident home (§19.2): remaining balance, cert status, Storm Mode, records carried.
import { useEffect, useReducer, useState } from 'react';
import * as api from '../api';
import { Header } from '../components/Header';
import { StyleSheet, Text, View } from 'react-native';
import { syncManager } from '../sync/manager';
import {
  Button, Cell, colors, Columns, ErrorNote, font, Group, Label, Meter, MoneyRow, Muted, Screen, Status, wholeDollars,
} from '../components/ui';
import { useOnline } from '../hooks';
import { KEY_REF } from '../keys';
import { useNav } from '../nav';
import { verifyObject } from '../protocol';
import { getDisplayName, getServerPub } from '../settings';
import { countsByKind, nowS } from '../store/items';
import { currentPolicy } from '../store/policy';
import { latestCert, recentReceipts, saveCertVersion, walletState } from '../store/wallet';

const STORM_CAP = 5000;

export function WalletScreen() {
  const nav = useNav();
  const online = useOnline();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [, rerender] = useReducer((x: number) => x + 1, 0);
  useEffect(() => syncManager.subscribe(rerender), []);
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
    ? { text: 'Frozen. A shop found this money spent twice.', tone: 'red' as const }
    : expired
      ? { text: 'Expired. Renews when any phone gets online.', tone: 'amber' as const }
      : { text: 'Backed by Capital One', tone: 'green' as const };
  const storm = cert.cap_cents >= STORM_CAP;
  const stubs = recentReceipts(6);
  const name = getDisplayName();

  const allowance = (
    <View style={{ gap: 16 }}>
      <View style={styles.sheet} accessible accessibilityLabel={`${wholeDollars(left)} left to spend of ${wholeDollars(cert.cap_cents)}. ${status.text}.`}>
        <View style={styles.sheetTop}>
          <Text style={styles.book}>{name ? `${name}'s book` : 'Your book'}</Text>
          <Text style={styles.copyNo}>next copy no. {state.counter + 1}</Text>
        </View>
        <Text maxFontSizeMultiplier={1.15} style={styles.figure} adjustsFontSizeToFit numberOfLines={1}>{wholeDollars(left)}</Text>
        <Text style={styles.sheetSub}>left to spend offline</Text>
        <Meter value={state.cumCents} max={cert.cap_cents} color={colors.sheetFigure} track={colors.sheetEdge} />
        <Status text={status.text} tone={status.tone} />
      </View>
      <Button title="Pay a shop" big onPress={() => nav.go({ name: 'pay' })} disabled={frozen || expired || left === 0} />
      <Group>
        <View style={{ paddingHorizontal: 18, paddingVertical: 4 }}>
          <MoneyRow label="Held by Capital One" note={storm ? 'Storm Mode escrow' : 'Escrow for offline payments'} value={wholeDollars(cert.cap_cents)} />
          <MoneyRow label="Signed offline" note={`${state.counter} ${state.counter === 1 ? 'payment' : 'payments'} from this phone`} value={`−${wholeDollars(state.cumCents)}`} />
          <MoneyRow label="Left to spend" value={wholeDollars(left)} strong />
        </View>
      </Group>
      <Muted>Counts when you sign. Charged only once the shop's record reaches the bank.</Muted>
    </View>
  );

  const activity = (
    <View style={{ gap: 16 }}>
      <View style={{ gap: 4 }}>
        <Label>Activity</Label>
        {stubs.length === 0 ? (
          <Muted>No payments yet.</Muted>
        ) : (
          stubs.map((r) => (
            <View key={r.tagHash} style={styles.stub}>
              <View style={{ flex: 1, minWidth: 0 }}>
                <Text style={styles.stubShop} numberOfLines={1}>{r.shop}</Text>
                <Text style={styles.stubMeta}>
                  Signed offline · copy {r.counter} · {new Date(r.ts * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
                </Text>
              </View>
              <Text maxFontSizeMultiplier={1.15} style={styles.stubAmount}>{wholeDollars(r.amountCents)}</Text>
            </View>
          ))
        )}
      </View>
      <Group>
        <Cell
          title="Storm Mode"
          detail={storm ? `On · Capital One holds ${wholeDollars(cert.cap_cents)}` : `Raise limit to ${wholeDollars(STORM_CAP)}`}
          accessory={storm ? <Text style={styles.on}>On</Text> : undefined}
        />
        <Cell title="Records to deliver" detail="Phones pass them on until one is online" value={String(carrying)} onPress={() => nav.go({ name: 'records' })} />
        <Cell title="Certificate" detail={expired ? 'Renews when any phone is online' : `Renews in ${hoursLeft} hours`} value={`v${cert.cert_ver}`} />
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
    </View>
  );

  return (
    <Screen>
      <Header />
      <Columns left={allowance} right={activity} ratio={1.1} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  sheet: {
    backgroundColor: colors.sheet, borderRadius: 8, padding: 20, gap: 10,
    borderBottomWidth: 4, borderBottomColor: colors.sheetEdge, // the stack of copies underneath
  },
  sheetTop: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'baseline', columnGap: 12 },
  book: { fontFamily: font.bold, fontSize: 17, color: colors.sheetInk },
  copyNo: { fontFamily: font.regular, fontSize: 15, color: colors.sheetMuted, fontVariant: ['tabular-nums'] },
  figure: { fontFamily: font.display, fontSize: 132, lineHeight: 146, color: colors.sheetFigure, fontVariant: ['tabular-nums'] },
  sheetSub: { fontFamily: font.regular, fontSize: 17, lineHeight: 24, color: colors.sheetInk, marginBottom: 6 },
  stub: { flexDirection: 'row', alignItems: 'center', paddingVertical: 12, gap: 12 },
  stubShop: { fontFamily: font.bold, fontSize: 18, color: colors.ink },
  stubMeta: { fontFamily: font.regular, fontSize: 15, color: colors.muted, fontVariant: ['tabular-nums'] },
  stubAmount: { fontFamily: font.display, fontSize: 34, color: colors.carbon, fontVariant: ['tabular-nums'] },
  on: { fontFamily: font.bold, fontSize: 17, color: colors.carbon },
});
