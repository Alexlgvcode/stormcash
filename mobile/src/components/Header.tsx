// Header: logo (long-press opens the hidden demo menu, §19.2), demo label, online and nearby status.
import { useEffect, useReducer } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useOnline } from '../hooks';
import { useNav } from '../nav';
import { getDemoLabel } from '../settings';
import { syncManager } from '../sync/manager';
import { colors, font, Status } from './ui';

const LABEL_NAMES: Record<string, string> = { MAYA: 'Maya', PHARMACY: 'Pharmacy', GAS_STATION: 'Gas Station' };

export function Logo({ light }: { light?: boolean }) {
  return (
    <Text maxFontSizeMultiplier={1.15} style={[styles.word, light && { color: '#fff' }]} accessibilityRole="header">StormCash</Text>
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
        {label ? <Text style={styles.label}>Demo phone: {LABEL_NAMES[label] ?? label}</Text> : null}
      </Pressable>
      <View style={styles.right}>
        <Status text={online ? 'Online' : 'Offline'} tone={online ? 'green' : 'amber'} />
        {nearby > 0 ? <Status text={`${nearby} nearby`} tone="blue" /> : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start' },
  word: { fontFamily: font.display, fontSize: 32, lineHeight: 34, color: colors.carbon },
  label: { fontFamily: font.regular, fontSize: 15, color: colors.muted, marginTop: 2 },
  right: { alignItems: 'flex-end', gap: 6 },
});
