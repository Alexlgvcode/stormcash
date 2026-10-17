// Header: logo (long-press opens the hidden demo menu, §19.2), demo label, online and nearby status.
import { useEffect, useReducer } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useOnline } from '../hooks';
import { useNav } from '../nav';
import { getDemoLabel } from '../settings';
import { syncManager } from '../sync/manager';
import { colors, Pill } from './ui';

const LABEL_NAMES: Record<string, string> = { MAYA: 'Maya', PHARMACY: 'Pharmacy', GAS_STATION: 'Gas Station' };

export function Logo({ light }: { light?: boolean }) {
  return (
    <View style={styles.logoRow}>
      <View style={styles.mark}>
        <Text style={styles.markText}>S</Text>
      </View>
      <Text style={[styles.word, light && { color: '#fff' }]}>
        Storm<Text style={{ color: light ? '#9DB4FF' : colors.primary }}>Cash</Text>
      </Text>
    </View>
  );
}

export function Header() {
  const nav = useNav();
  const online = useOnline();
  const [, rerender] = useReducer((x: number) => x + 1, 0);
  useEffect(() => syncManager.subscribe(rerender), []);
  const label = getDemoLabel();
  const nearby = syncManager.status.connected.length;
  return (
    <View style={styles.row}>
      <Pressable onLongPress={() => nav.go({ name: 'demo' })} delayLongPress={600} accessibilityHint="Long-press for the demo menu">
        <Logo />
        {label ? <Text style={styles.label}>{LABEL_NAMES[label] ?? label} · demo phone</Text> : null}
      </Pressable>
      <View style={styles.right}>
        <Pill text={online ? 'Online' : 'Offline'} tone={online ? 'green' : 'neutral'} dot />
        {nearby > 0 ? <Pill text={`${nearby} nearby`} tone="blue" dot /> : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start' },
  logoRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  mark: { width: 30, height: 30, borderRadius: 9, backgroundColor: colors.primary, alignItems: 'center', justifyContent: 'center' },
  markText: { color: '#fff', fontWeight: '900', fontSize: 18 },
  word: { fontSize: 22, fontWeight: '800', color: colors.ink, letterSpacing: -0.3 },
  label: { fontSize: 13, color: colors.muted, marginTop: 4, marginLeft: 38 },
  right: { alignItems: 'flex-end', gap: 6 },
});
