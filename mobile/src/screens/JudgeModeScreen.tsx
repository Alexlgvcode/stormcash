// Judge mode: the attacker tool (§19.3). Rolls the wallet back so the judge can try to spend twice.
import * as Haptics from 'expo-haptics';
import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Big, Button, Card, colors, Field, font, Label, Muted, Screen, wholeDollars } from '../components/ui';
import { useNav } from '../nav';
import { latestCert, rollBack, walletState, type RollbackMode } from '../store/wallet';

export function JudgeModeScreen() {
  const nav = useNav();
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const state = walletState();
  const cert = latestCert();
  const left = cert && state ? cert.cap_cents - state.cumCents : 0;

  const run = (mode: RollbackMode) => {
    const ok = rollBack(mode);
    Haptics.notificationAsync(ok ? Haptics.NotificationFeedbackType.Warning : Haptics.NotificationFeedbackType.Error)
      .catch(() => {});
    setMessage(
      !ok
        ? { ok, text: 'Nothing to roll back yet. Make a payment first.' }
        : mode === 'reuse'
          ? { ok, text: 'Wallet restored to before the last payment: same money, same counter. Now try spending it next door.' }
          : { ok, text: 'Wallet restored and the counter skipped ahead. Now try spending it next door.' },
    );
    nav.refresh();
  };

  return (
    <Screen tone="dark">
      <View style={styles.banner}>
        <Text style={styles.bannerText}>Demo: attacker tool</Text>
      </View>
      <Text style={styles.lead}>You're Maya, and you're cheating. Try to spend the same money twice.</Text>

      <Card style={{ backgroundColor: colors.navyRaised }}>
        <Label color={colors.onNavyMuted}>Wallet now</Label>
        <Big color="#fff">{wholeDollars(left)}</Big>
        <Field light label="Counter" value={String(state?.counter ?? 0)} />
        <Field light label="Spent" value={wholeDollars(state?.cumCents ?? 0)} last />
      </Card>

      <Button title="Reuse the money" subtitle="Restore the wallet to before the last payment" kind="danger" big onPress={() => run('reuse')} />
      <Button title="Be clever" subtitle="Restore, then skip the counter ahead" kind="danger" big onPress={() => run('clever')} />

      {message ? (
        <View style={[styles.note, { backgroundColor: message.ok ? '#7A4A0A' : '#7A1712' }]}>
          <Text style={styles.noteText}>{message.text}</Text>
        </View>
      ) : null}

      <Muted color="#98A2B3">This is what a modified app or a restored backup could do. Every offline system has to handle it.</Muted>

      <Button title="Pay a shop" kind="light" big onPress={() => nav.go({ name: 'pay' })} />
      <Button title="Back" kind="light" onPress={nav.home} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  banner: { backgroundColor: colors.red, paddingVertical: 14, borderRadius: 999 },
  bannerText: { color: '#fff', fontFamily: font.bold, fontSize: 19, textAlign: 'center', letterSpacing: -0.2 },
  lead: { color: '#fff', fontFamily: font.bold, fontSize: 24, lineHeight: 30, letterSpacing: -0.5 },
  note: { borderRadius: 16, padding: 16 },
  noteText: { color: '#fff', fontFamily: font.medium, fontSize: 16, lineHeight: 22 },
});
