// Judge mode: the attacker tool (§19.3). Rolls the wallet back so the judge can try to spend twice.
import * as Haptics from 'expo-haptics';
import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Big, Button, Card, colors, Field, font, Label, Muted, Screen, wholeDollars, TopBar } from '../components/ui';
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
          ? { ok, text: 'Rolled back. Now pay again.' }
          : { ok, text: 'Rolled back, counter skipped. Now pay again.' },
    );
    nav.refresh();
  };

  return (
    <Screen tone="dark">
      <TopBar onBack={nav.home} />
      <View style={styles.banner}>
        <Text style={styles.bannerText}>Demo: attacker tool</Text>
      </View>
      <Text maxFontSizeMultiplier={1.15} style={styles.lead}>Spend the same money twice.</Text>

      <Card style={{ backgroundColor: colors.navyRaised }}>
        <Label color={colors.onNavyMuted}>Wallet now</Label>
        <Big color="#fff">{wholeDollars(left)}</Big>
        <Field light label="Counter" value={String(state?.counter ?? 0)} />
        <Field light label="Spent" value={wholeDollars(state?.cumCents ?? 0)} last />
      </Card>

      <Button title="Reuse the money" subtitle="Undo the last payment" kind="danger" big onPress={() => run('reuse')} />
      <Button title="Be clever" subtitle="Undo it, skip a number" kind="danger" big onPress={() => run('clever')} />

      {message ? (
        <View style={[styles.note, { backgroundColor: message.ok ? '#7A4A0A' : '#7A1712' }]}>
          <Text style={styles.noteText}>{message.text}</Text>
        </View>
      ) : null}

      <Muted color="#98A2B3">What a hacked app or restored backup could do.</Muted>

      <Button title="Pay a shop" kind="light" big onPress={() => nav.go({ name: 'pay' })} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  banner: { backgroundColor: colors.refuseBg, paddingVertical: 14, borderRadius: 999 },
  bannerText: { color: '#fff', fontFamily: font.bold, fontSize: 19, textAlign: 'center', letterSpacing: -0.2 },
  lead: { color: '#fff', fontFamily: font.displayBold, fontSize: 28, lineHeight: 31, letterSpacing: -0.6 },
  note: { borderRadius: 16, padding: 16 },
  noteText: { color: '#fff', fontFamily: font.medium, fontSize: 16, lineHeight: 22 },
});
