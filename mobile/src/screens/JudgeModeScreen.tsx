// Judge mode: the attacker tool (§19.3). Rolls the wallet back so the judge can try to spend twice.
import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Big, Body, Button, colors, Muted, Screen, wholeDollars } from '../components/ui';
import { useNav } from '../nav';
import { latestCert, rollBack, walletState, type RollbackMode } from '../store/wallet';

export function JudgeModeScreen() {
  const nav = useNav();
  const [message, setMessage] = useState<string | null>(null);
  const state = walletState();
  const cert = latestCert();
  const left = cert && state ? cert.cap_cents - state.cumCents : 0;

  const run = (mode: RollbackMode) => {
    const ok = rollBack(mode);
    setMessage(
      !ok
        ? 'Nothing to roll back yet. Make a payment first.'
        : mode === 'reuse'
          ? 'Wallet restored to before the last payment. Same money, same counter. Try spending it next door.'
          : 'Wallet restored and the counter skipped ahead. Try spending it next door.',
    );
    nav.refresh();
  };

  return (
    <Screen>
      <View style={styles.banner}>
        <Text style={styles.bannerText}>Demo: attacker tool</Text>
      </View>
      <Big>{wholeDollars(left)} left</Big>
      <Muted>Counter {state?.counter ?? 0}</Muted>
      <Body>This is what a modified app or a restored backup could do.</Body>

      <Button title="Roll back wallet: Reuse the money" kind="danger" onPress={() => run('reuse')} />
      <Button title="Roll back wallet: Be clever (skip the counter)" kind="danger" onPress={() => run('clever')} />

      {message ? <Body color={colors.red}>{message}</Body> : null}

      <Button title="Pay" onPress={() => nav.go({ name: 'pay' })} />
      <Button title="Back" kind="secondary" onPress={nav.home} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  banner: { backgroundColor: colors.red, padding: 12, borderRadius: 10 },
  bannerText: { color: '#fff', fontSize: 20, fontWeight: '800', textAlign: 'center' },
});
